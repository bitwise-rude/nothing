from flask import Flask, render_template, session, redirect, url_for, request, flash
from datetime import datetime, date
from flask_socketio import SocketIO, emit, join_room, leave_room
import qrcode
from memory import *

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app)

# Load data from memory
userCredentials, toConfirmTransaction, transactions, userData = load()
debtPayList = None
active_users = set()

@app.route("/login", methods=["POST", "GET"])
def login():
    if request.method == "GET":
        return render_template('login.html')
    else:
        username = request.form.get('username')
        password = request.form.get('password')

        if password == userCredentials.get(username):
            session["username"] = username
            return redirect("/")
        else:
            flash("Incorrect Username or password", 'error')
            return redirect('/login')

@app.route('/change-password', methods=["POST", "GET"])
def changePassword():
    if request.method == "GET":
        return render_template("password.html")
    else:
        username = session.get('username')

        cpass = request.form.get('current_password')
        newPass = request.form.get('new_password')
        conPass = request.form.get('confirm_password')

        if username:
            if cpass == userCredentials[username]:
                if newPass == conPass:
                    session.clear()
                    userCredentials[username] = newPass
                    save(userCredentials, toConfirmTransaction, transactions, userData)
                    flash("Password Changed Successfully. Log in again!", 'success')
                    return redirect('/login')
                else:
                    flash("New Password and Re-entered password are not same!", "error")
                    return redirect('/change-password')
            else:
                flash("Incorrect Password!", 'error')
                return redirect('/change-password')
        else:
            session.clear()
            return redirect('/')

@app.route('/logout')
def logout():
    session.clear()
    flash("Successfully Logged out! Please Login again!", "success")
    return redirect("/login")

@app.route('/')
def index():
    # Check if user is logged in
    if not session.get('username'):
        return redirect(url_for('login'))
    
    # Get current user's username
    current_username = session.get('username')
    
    # Find the other user's data
    otherName = None
    otherData = None
    for data in userData.keys():
        if data != current_username:
            otherName = data
            otherData = userData[data]
            break
    
    # Get recent transactions (max 10)
    recent_transactions = transactions[::-1][0:10] if len(transactions) > 10 else transactions
    
    # Get pending transactions for this user
    pending_transactions = [t for t in toConfirmTransaction]
    
    return render_template(
        'dashboard.html',
        current_date=date.today().isoformat(),
        history=recent_transactions,
        selfName=current_username,
        selfData=userData[current_username],
        otherName=otherName,
        otherData=otherData,
        pending=pending_transactions,
        active_users=active_users
    )

@socketio.on('generate')
def generateQR(inputDebt, otherName, userName):
    print(inputDebt, otherName, userName)
    toGenerate = {
        "bankCode": "GLBBNPKA",
        "accountName": userData[otherName]['accountName'],
        "accountNumber": userData[otherName]['accountNumber'],
        "amount": inputDebt,
        "remarks": "Debt Paid to " + otherName
    }
    qrcode.make(json.dumps(toGenerate)).save('static\\' + userName + ".png")
    emit('onGenerate')

@socketio.on('connect')
def handle_connect():
    if 'username' in session:
        username = session['username']
        # Create a room for the user
        join_room(username)
        # Mark this user as active
        active_users.add(username)
        # Broadcast to all users that this user is active
        emit('user_status', {'username': username, 'status': 'online'}, broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    if 'username' in session:
        username = session['username']
        # Remove user from active_users
        if username in active_users:
            active_users.remove(username)
        # Leave the user-specific room
        leave_room(username)
        # Broadcast to all users that this user is offline
        emit('user_status', {'username': username, 'status': 'offline'}, broadcast=True)

@socketio.on('firstConnection')
def handleFirstConnection(data):
    print(data["username"], 'is connected')
    
    # Add to active users
    active_users.add(data["username"])
    
    # Join a room specific to this user
    join_room(data["username"])

    # Show pending transactions if any
    for tx in toConfirmTransaction:
        if tx['username'] != data['username']:  # Show transactions created by others
            emit('verifyTransaction', tx)
        else:
            emit('warning', f"Your Transaction for '{tx['title']}' is waiting for verification.")

    # Notify everyone about this user's connection
    emit("UserConnected", {"username": data["username"]}, room=request.sid)
    emit("active_users_update", list(active_users), broadcast=True)

@socketio.on('newTransaction')
def addNewTransaction(data):
    data.update({"id": len(toConfirmTransaction), 'done': 0})
    toConfirmTransaction.append(data)
    save(userCredentials, toConfirmTransaction, transactions, userData)
    
    # Broadcast to everyone except the sender
    for username in active_users:
        if username != data['username']:  # Don't send to the creator
            emit('verifyTransaction', data, room=username)
    
    # Send confirmation to the creator
    emit('transactionCreated', data)

@socketio.on('deleteTransaction')
def deleteTransaction(transaction_id):
    # Find and remove the transaction
    transaction_to_delete = None
    for tx in toConfirmTransaction:
        if tx["id"] == transaction_id:
            transaction_to_delete = tx
            break
    
    if transaction_to_delete:
        toConfirmTransaction.remove(transaction_to_delete)
        save(userCredentials, toConfirmTransaction, transactions, userData)
        # Notify all users about the deleted transaction
        emit('transactionDeleted', {'id': transaction_id}, broadcast=True)
        return True
    return False

def addHistory(data):
    transactions.append(data)
    for stfs in userData.keys():
        if stfs == data['username']:
            doer = data['username']
        else:
            other = stfs
    if data['amount'] / 2 > data['yourPay']:
        userData[doer]['toPay'] += abs(data['amount'] / 2 - data['yourPay'])
    elif data['amount'] / 2 < data['yourPay']:
        userData[other]['toPay'] += abs(data['amount'] / 2 - data['yourPay'])
    
    # check for debt re matching
    if userData[doer]['toPay'] >= userData[other]['toPay'] and (userData[doer]['toPay'] != 0 and userData[other]['toPay'] != 0):
        userData[doer]['toPay'] = userData[doer]['toPay'] - userData[other]['toPay']
        userData[other]['toPay'] = 0
    
    if userData[other]['toPay'] >= userData[doer]['toPay'] and (userData[doer]['toPay'] != 0 and userData[other]['toPay'] != 0):
        userData[other]['toPay'] = userData[other]['toPay'] - userData[doer]['toPay']
        userData[doer]['toPay'] = 0
    
    save(userCredentials, toConfirmTransaction, transactions, userData)

@socketio.on('newDebtPay')
def debtPay(who, much):
    global debtPayList
    
    # Check if both users are active
    other_user = None
    for username in userData.keys():
        if username != who:
            other_user = username
            break
    
    if who in active_users and other_user in active_users:
        # Reset debtPayList to allow new debt payment
        debtPayList = [who, much, 0]
        emit("verifyDebt", (who, much), broadcast=True)
        return {"success": True, "message": "Debt payment request sent"}
    else:
        return {"success": False, "message": "Both users must be online to process debt payments"}

@socketio.on('confirmTransaction')
def confirmTransaction(data):
    for ts in toConfirmTransaction:
        if ts["id"] == data['id']:
            print("CONFIRMED by 1")
            ts['done'] += 1

            if ts['done'] >= 2:
                print("TOTALLY CONFIRMED")
                toConfirmTransaction.remove(ts)
                addHistory(data)

                # reload to refresh but will add other things to add
                emit("refresh", broadcast=True)
                save(userCredentials, toConfirmTransaction, transactions, userData)
                return {"success": True, "message": "Transaction confirmed successfully"}
    
    return {"success": False, "message": "Transaction not found"}

@socketio.on('rejectTransaction')
def rejectTransaction(data):
    for ts in toConfirmTransaction:
        if ts["id"] == data['id']:
            toConfirmTransaction.remove(ts)
            save(userCredentials, toConfirmTransaction, transactions, userData)
            emit("transactionRejected", {"id": data['id']}, broadcast=True)
            return {"success": True, "message": "Transaction rejected"}
    
    return {"success": False, "message": "Transaction not found"}

def addHistoryDebt(who, whom):
    transactions.append({
        "date": str(datetime.now()),
        "username": who,
        "title": 'Debt Payment',
        "amount": whom,
        "remarks": "Debt payment",
        'yourPay': 0,
    })
    userData[who]['toPay'] -= whom
    save(userCredentials, toConfirmTransaction, transactions, userData)

@socketio.on('confirmDebtPay')
def confirmDebtPay(who, whom):
    global debtPayList
    
    if debtPayList is None:
        return {"success": False, "message": "No debt payment request found"}
    
    print("CONFIRMED by 1")
    debtPayList[2] += 1 

    if debtPayList[2] >= 2:
        print("TOTALLY CONFIRMED")
        addHistoryDebt(who, whom)
        
        # Reset debtPayList to allow new requests
        debtPayList = None
        
        # Reload to refresh
        emit("refresh", broadcast=True)
        save(userCredentials, toConfirmTransaction, transactions, userData)
        return {"success": True, "message": "Debt payment confirmed"}
    
    return {"success": True, "message": "Waiting for final confirmation"}

@socketio.on('rejectDebtPay')
def rejectDebtPay():
    global debtPayList
    
    if debtPayList is not None:
        # Reset debtPayList to allow new requests
        debtPayList = None
        emit("debtPayRejected", broadcast=True)
        return {"success": True, "message": "Debt payment rejected"}
    
    return {"success": False, "message": "No debt payment request found"}


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host='0.0.0.0', port=port)
