from flask import Flask, render_template, session, redirect, url_for, request, flash
from datetime import datetime, date
from flask_socketio import SocketIO, emit, join_room, leave_room
import qrcode
import json
import os
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
def generateQR(data):
    try:
        # Extract data properly
        inputDebt = float(data.get('inputDebt', 0))
        otherName = data.get('otherName', '')
        userName = data.get('userName', '')
        
        print(f"Generating QR for: Debt={inputDebt}, Other={otherName}, User={userName}")
        
        # Validate inputs
        if not inputDebt or inputDebt <= 0:
            emit('qrError', {'message': 'Invalid debt amount'})
            return
            
        if not otherName or otherName not in userData:
            emit('qrError', {'message': 'Invalid recipient'})
            return
        
        # Format amount properly (ensure 2 decimal places for currency)
        formatted_amount = "{:.2f}".format(inputDebt)
        
        # Create QR code data
        toGenerate = {
            "bankCode": "GLBBNPKA",
            "accountName": userData[otherName]['accountName'],
            "accountNumber": userData[otherName]['accountNumber'],
            "amount": formatted_amount,  # Use formatted amount
            "remarks": f"Debt Payment to {otherName}"
        }
        
        # Ensure static directory exists
        static_dir = 'static'
        if not os.path.exists(static_dir):
            os.makedirs(static_dir)
        
        # Generate QR code with proper JSON formatting
        qr_data = json.dumps(toGenerate, separators=(',', ':'))  # Compact JSON
        qr_code = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr_code.add_data(qr_data)
        qr_code.make(fit=True)
        
        # Create QR code image
        qr_image = qr_code.make_image(fill_color="black", back_color="white")
        qr_filename = f"{userName}_payment.png"
        qr_path = os.path.join(static_dir, qr_filename)
        qr_image.save(qr_path)
        
        print(f"QR code saved to: {qr_path}")
        print(f"QR code data: {qr_data}")
        
        emit('onGenerate', {
            'success': True, 
            'filename': qr_filename,
            'amount': formatted_amount,
            'recipient': otherName
        })
        
    except Exception as e:
        print(f"Error generating QR code: {str(e)}")
        emit('qrError', {'message': f'Failed to generate QR code: {str(e)}'})

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
    
    # Get the two users
    doer = data['username']
    other = None
    for username in userData.keys():
        if username != doer:
            other = username
            break
    
    if not other:
        print("Error: Could not find other user")
        return
    
    # Calculate debt changes
    total_amount = float(data['amount'])
    user_paid = float(data['yourPay'])
    fair_share = total_amount / 2
    
    print(f"Transaction: Total={total_amount}, UserPaid={user_paid}, FairShare={fair_share}")
    
    # Calculate who owes what
    if user_paid > fair_share:
        # User paid more than their share, other user owes them
        amount_owed = user_paid - fair_share
        userData[other]['toPay'] += amount_owed
        print(f"{other} now owes {doer} an additional {amount_owed}")
    elif user_paid < fair_share:
        # User paid less than their share, user owes the other
        amount_owed = fair_share - user_paid
        userData[doer]['toPay'] += amount_owed
        print(f"{doer} now owes {other} an additional {amount_owed}")
    # If user_paid == fair_share, no debt change needed
    
    # Debt netting - if both users owe each other, net them out
    if userData[doer]['toPay'] > 0 and userData[other]['toPay'] > 0:
        if userData[doer]['toPay'] >= userData[other]['toPay']:
            userData[doer]['toPay'] -= userData[other]['toPay']
            userData[other]['toPay'] = 0
            print(f"After netting: {doer} owes {userData[doer]['toPay']}, {other} owes 0")
        else:
            userData[other]['toPay'] -= userData[doer]['toPay']
            userData[doer]['toPay'] = 0
            print(f"After netting: {doer} owes 0, {other} owes {userData[other]['toPay']}")
    
    save(userCredentials, toConfirmTransaction, transactions, userData)

@socketio.on('newDebtPay')
def debtPay(data):
    global debtPayList
    
    try:
        who = data.get('who', '')
        much = float(data.get('much', 0))
        
        print(f"Debt payment request: {who} wants to pay {much}")
        
        if much <= 0:
            emit('debtPayError', {'message': 'Invalid payment amount'})
            return
        
        # Check if user has enough debt to pay
        if userData[who]['toPay'] < much:
            emit('debtPayError', {'message': f'You only owe {userData[who]["toPay"]:.2f}'})
            return
        
        # Check if both users are active
        other_user = None
        for username in userData.keys():
            if username != who:
                other_user = username
                break
        
        if who in active_users and other_user in active_users:
            # Reset debtPayList to allow new debt payment
            debtPayList = [who, much, 0]
            emit("verifyDebt", {'who': who, 'amount': much}, broadcast=True)
            emit('debtPaySuccess', {'message': 'Debt payment request sent'})
        else:
            emit('debtPayError', {'message': 'Both users must be online to process debt payments'})
            
    except Exception as e:
        print(f"Error in debt payment: {str(e)}")
        emit('debtPayError', {'message': 'Invalid payment data'})

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

def addHistoryDebt(who, amount):
    # Add debt payment to transaction history
    transactions.append({
        "date": str(datetime.now()),
        "username": who,
        "title": 'Debt Payment',
        "amount": amount,
        "remarks": "Debt payment",
        'yourPay': amount,  # They paid the full amount since it's a debt payment
    })
    
    # Reduce the debt
    userData[who]['toPay'] = max(0, userData[who]['toPay'] - amount)
    print(f"{who} paid {amount}, remaining debt: {userData[who]['toPay']}")
    
    save(userCredentials, toConfirmTransaction, transactions, userData)

@socketio.on('confirmDebtPay')
def confirmDebtPay(data):
    global debtPayList
    
    try:
        who = data.get('who', '')
        amount = float(data.get('amount', 0))
        
        if debtPayList is None:
            emit('debtPayError', {'message': 'No debt payment request found'})
            return
        
        print("CONFIRMED by 1")
        debtPayList[2] += 1 

        if debtPayList[2] >= 2:
            print("TOTALLY CONFIRMED")
            addHistoryDebt(who, amount)
            
            # Reset debtPayList to allow new requests
            debtPayList = None
            
            # Reload to refresh
            emit("refresh", broadcast=True)
            save(userCredentials, toConfirmTransaction, transactions, userData)
            emit('debtPaySuccess', {'message': 'Debt payment confirmed'})
        else:
            emit('debtPaySuccess', {'message': 'Waiting for final confirmation'})
            
    except Exception as e:
        print(f"Error confirming debt payment: {str(e)}")
        emit('debtPayError', {'message': 'Error processing debt payment'})

@socketio.on('rejectDebtPay')
def rejectDebtPay():
    global debtPayList
    
    if debtPayList is not None:
        # Reset debtPayList to allow new requests
        debtPayList = None
        emit("debtPayRejected", broadcast=True)
        emit('debtPaySuccess', {'message': 'Debt payment rejected'})
    else:
        emit('debtPayError', {'message': 'No debt payment request found'})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host='0.0.0.0', port=port)
