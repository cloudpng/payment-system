from flask import Flask, render_template, request, redirect, url_for, flash, session
from functools import wraps
from datetime import datetime
import os
import uuid
import enum

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'payment-system-secret-key-2026')

# ============== DATABASE ==============
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey, Enum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker

Base = declarative_base()

class PaymentStatus(enum.Enum):
    INITIATED = "INITIATED"
    FF3_FF4_RAISED = "FF3_FF4_RAISED"
    FULLY_AUTHORIZED = "FULLY_AUTHORIZED"
    FUNDS_AVAILABLE = "FUNDS_AVAILABLE"
    DEFERRED_INSUFFICIENT_FUNDS = "DEFERRED_INSUFFICIENT_FUNDS"
    CHEQUE_GENERATED = "CHEQUE_GENERATED"
    CHEQUE_READY_FOR_DISBURSEMENT = "CHEQUE_READY_FOR_DISBURSEMENT"
    DISBURSED = "DISBURSED"
    COMPLETED = "COMPLETED"

class UserRole(enum.Enum):
    REGISTRAR = "REGISTRAR"
    DIRECTOR_CORPORATE_SERVICES = "DIRECTOR_CORPORATE_SERVICES"
    ACCOUNTS_OFFICER = "ACCOUNTS_OFFICER"
    FINANCE_OFFICER = "FINANCE_OFFICER"

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    full_name = Column(String(100), nullable=False)
    role = Column(Enum(UserRole), nullable=False)
    is_active = Column(Boolean, default=True)

class Payment(Base):
    __tablename__ = 'payments'
    id = Column(Integer, primary_key=True)
    payment_id = Column(String(20), unique=True, nullable=False)
    date_initiated = Column(DateTime, default=datetime.utcnow)
    initiated_by_id = Column(Integer, ForeignKey('users.id'))
    payment_document_ref = Column(String(50), nullable=False)
    payee_name = Column(String(200), nullable=False)
    amount = Column(Float, nullable=False)
    purpose = Column(Text, nullable=False)
    status = Column(Enum(PaymentStatus), default=PaymentStatus.INITIATED)
    ff3_raised = Column(Boolean, default=False)
    ff4_raised = Column(Boolean, default=False)

class Authorization(Base):
    __tablename__ = 'authorizations'
    id = Column(Integer, primary_key=True)
    payment_id = Column(Integer, ForeignKey('payments.id'), unique=True)
    ff3_registrar_id = Column(Integer, ForeignKey('users.id'))
    ff3_registrar_date = Column(DateTime)
    ff3_director_id = Column(Integer, ForeignKey('users.id'))
    ff3_director_date = Column(DateTime)
    ff4_registrar_id = Column(Integer, ForeignKey('users.id'))
    ff4_registrar_date = Column(DateTime)
    ff4_director_id = Column(Integer, ForeignKey('users.id'))
    ff4_director_date = Column(DateTime)
    fully_authorized = Column(Boolean, default=False)

class FundCheck(Base):
    __tablename__ = 'fund_checks'
    id = Column(Integer, primary_key=True)
    payment_id = Column(Integer, ForeignKey('payments.id'), unique=True)
    commercial_bank_balance = Column(Float, default=0.0)
    amount_required = Column(Float, nullable=False)
    bank_sufficient = Column(Boolean, default=False)
    routing_decision = Column(String(20))

class Cheque(Base):
    __tablename__ = 'cheques'
    id = Column(Integer, primary_key=True)
    payment_id = Column(Integer, ForeignKey('payments.id'), unique=True)
    cheque_number = Column(String(20), unique=True, nullable=False)
    registrar_signature_id = Column(Integer, ForeignKey('users.id'))
    director_signature_id = Column(Integer, ForeignKey('users.id'))
    custody_with_director = Column(Boolean, default=False)

class Disbursement(Base):
    __tablename__ = 'disbursements'
    id = Column(Integer, primary_key=True)
    payment_id = Column(Integer, ForeignKey('payments.id'), unique=True)
    disbursement_method = Column(String(20))
    register_page_number = Column(Integer)
    register_entry_number = Column(Integer)
    bank_receipt_recorded = Column(Boolean, default=False)

class Reconciliation(Base):
    __tablename__ = 'reconciliations'
    id = Column(Integer, primary_key=True)
    reconciliation_id = Column(String(30), unique=True, nullable=False)
    month = Column(String(10), nullable=False)
    year = Column(Integer, nullable=False)
    opening_bank_balance = Column(Float, nullable=False)
    closing_bank_balance = Column(Float, nullable=False)
    register_total_payments = Column(Float, default=0.0)
    outstanding_cheques_count = Column(Integer, default=0)
    outstanding_cheques_amount = Column(Float, default=0.0)
    adjusted_bank_balance = Column(Float)
    adjusted_register_balance = Column(Float)
    variance = Column(Float)
    reconciled = Column(Boolean, default=False)

# Initialize database
engine = create_engine('sqlite:///payment_system.db')
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)

# ============== DEMO DATA ==============
db = Session()
users = [
    User(username='registrar', full_name='The Registrar', role=UserRole.REGISTRAR),
    User(username='director', full_name='Director, Corporate Services', role=UserRole.DIRECTOR_CORPORATE_SERVICES),
    User(username='accounts', full_name='Accounts Officer', role=UserRole.ACCOUNTS_OFFICER),
    User(username='finance', full_name='Finance Officer', role=UserRole.FINANCE_OFFICER),
]
for user in users:
    existing = db.query(User).filter_by(username=user.username).first()
    if not existing:
        db.add(user)
db.commit()

# ============== HELPERS ==============
def get_db():
    return Session()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in first.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def role_required(roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if session.get('user_role') not in roles:
                flash('Access denied.', 'danger')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated
    return decorator

# ============== ROUTES ==============
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        db = get_db()
        user = db.query(User).filter_by(username=username).first()
        if user and user.is_active and password == user.role.value:
            session['user_id'] = user.id
            session['user_name'] = user.full_name
            session['user_role'] = user.role.value
            flash(f'Welcome, {user.full_name}!', 'success')
            return redirect(url_for('dashboard'))
        flash('Invalid credentials.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard():
    db = get_db()
    total = db.query(Payment).count()
    completed = db.query(Payment).filter_by(status=PaymentStatus.COMPLETED).count()
    deferred = db.query(Payment).filter_by(status=PaymentStatus.DEFERRED_INSUFFICIENT_FUNDS).count()
    pending = db.query(Payment).filter(Payment.status.in_([
        PaymentStatus.INITIATED, PaymentStatus.FF3_FF4_RAISED,
        PaymentStatus.FULLY_AUTHORIZED, PaymentStatus.CHEQUE_GENERATED
    ])).count()
    recent = db.query(Payment).order_by(Payment.date_initiated.desc()).limit(5).all()
    return render_template('dashboard.html', total=total, completed=completed,
                         deferred=deferred, pending=pending, recent=recent,
                         bank_balance=27000.0, user_role=session.get('user_role'))

@app.route('/payments')
@login_required
def list_payments():
    db = get_db()
    payments = db.query(Payment).order_by(Payment.date_initiated.desc()).all()
    return render_template('payments.html', payments=payments)

@app.route('/payments/new', methods=['GET', 'POST'])
@login_required
@role_required(['REGISTRAR', 'DIRECTOR_CORPORATE_SERVICES'])
def new_payment():
    if request.method == 'POST':
        db = get_db()
        payment = Payment(
            payment_id=f"PAY-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:6].upper()}",
            initiated_by_id=session['user_id'],
            payment_document_ref=request.form['document_ref'],
            payee_name=request.form['payee_name'],
            amount=float(request.form['amount']),
            purpose=request.form['purpose'],
            status=PaymentStatus.FF3_FF4_RAISED,
            ff3_raised=True, ff4_raised=True
        )
        db.add(payment)
        db.commit()
        flash(f'Payment initiated: {payment.payment_id}', 'success')
        return redirect(url_for('view_payment', payment_id=payment.id))
    return render_template('new_payment.html')

@app.route('/payments/<int:payment_id>')
@login_required
def view_payment(payment_id):
    db = get_db()
    payment = db.query(Payment).get(payment_id)
    if not payment:
        flash('Payment not found.', 'danger')
        return redirect(url_for('list_payments'))
    
    auth = db.query(Authorization).filter_by(payment_id=payment_id).first()
    fund = db.query(FundCheck).filter_by(payment_id=payment_id).first()
    cheque = db.query(Cheque).filter_by(payment_id=payment_id).first()
    disb = db.query(Disbursement).filter_by(payment_id=payment_id).first()
    
    return render_template('payment_detail.html', payment=payment, auth=auth,
                         fund=fund, cheque=cheque, disb=disb)

@app.route('/payments/<int:payment_id>/authorize', methods=['POST'])
@login_required
@role_required(['REGISTRAR', 'DIRECTOR_CORPORATE_SERVICES'])
def authorize_payment(payment_id):
    db = get_db()
    payment = db.query(Payment).get(payment_id)
    document = request.form['document']
    
    auth = db.query(Authorization).filter_by(payment_id=payment_id).first()
    if not auth:
        auth = Authorization(payment_id=payment_id)
        db.add(auth)
    
    user_id = session['user_id']
    now = datetime.utcnow()
    
    if session['user_role'] == 'REGISTRAR':
        if document == 'FF3':
            auth.ff3_registrar_id = user_id
            auth.ff3_registrar_date = now
        elif document == 'FF4':
            auth.ff4_registrar_id = user_id
            auth.ff4_registrar_date = now
    else:
        if document == 'FF3':
            auth.ff3_director_id = user_id
            auth.ff3_director_date = now
        elif document == 'FF4':
            auth.ff4_director_id = user_id
            auth.ff4_director_date = now
    
    if (auth.ff3_registrar_id and auth.ff3_director_id and
        auth.ff4_registrar_id and auth.ff4_director_id):
        auth.fully_authorized = True
        payment.status = PaymentStatus.FULLY_AUTHORIZED
    
    db.commit()
    flash(f'{document} signed successfully.', 'success')
    return redirect(url_for('view_payment', payment_id=payment_id))

@app.route('/payments/<int:payment_id>/check-funds', methods=['POST'])
@login_required
@role_required(['ACCOUNTS_OFFICER', 'FINANCE_OFFICER'])
def check_funds(payment_id):
    db = get_db()
    payment = db.query(Payment).get(payment_id)
    
    bank_balance = 27000.0
    sufficient = bank_balance >= payment.amount
    
    fund = FundCheck(
        payment_id=payment_id,
        commercial_bank_balance=bank_balance,
        amount_required=payment.amount,
        bank_sufficient=sufficient,
        routing_decision='Commercial_Bank' if sufficient else 'DEFER'
    )
    db.add(fund)
    payment.status = PaymentStatus.FUNDS_AVAILABLE if sufficient else PaymentStatus.DEFERRED_INSUFFICIENT_FUNDS
    db.commit()
    
    flash('Funds available.' if sufficient else 'Insufficient funds. Deferred.', 'success' if sufficient else 'warning')
    return redirect(url_for('view_payment', payment_id=payment_id))

@app.route('/payments/<int:payment_id>/generate-cheque', methods=['POST'])
@login_required
@role_required(['ACCOUNTS_OFFICER', 'FINANCE_OFFICER'])
def generate_cheque(payment_id):
    db = get_db()
    cheque = Cheque(
        payment_id=payment_id,
        cheque_number=request.form['cheque_number']
    )
    db.add(cheque)
    db.query(Payment).get(payment_id).status = PaymentStatus.CHEQUE_GENERATED
    db.commit()
    flash(f'Cheque {request.form["cheque_number"]} generated.', 'success')
    return redirect(url_for('view_payment', payment_id=payment_id))

@app.route('/payments/<int:payment_id>/sign-cheque', methods=['POST'])
@login_required
@role_required(['REGISTRAR', 'DIRECTOR_CORPORATE_SERVICES'])
def sign_cheque(payment_id):
    db = get_db()
    cheque = db.query(Cheque).filter_by(payment_id=payment_id).first()
    user_id = session['user_id']
    
    if session['user_role'] == 'REGISTRAR':
        cheque.registrar_signature_id = user_id
    else:
        cheque.director_signature_id = user_id
    
    if cheque.registrar_signature_id and cheque.director_signature_id:
        cheque.custody_with_director = True
        db.query(Payment).get(payment_id).status = PaymentStatus.CHEQUE_READY_FOR_DISBURSEMENT
    
    db.commit()
    flash('Cheque signed.', 'success')
    return redirect(url_for('view_payment', payment_id=payment_id))

@app.route('/payments/<int:payment_id>/disburse', methods=['POST'])
@login_required
@role_required(['DIRECTOR_CORPORATE_SERVICES', 'ACCOUNTS_OFFICER'])
def disburse_payment(payment_id):
    db = get_db()
    disb = Disbursement(
        payment_id=payment_id,
        disbursement_method=request.form['method'],
        register_page_number=int(request.form['register_page']),
        register_entry_number=int(request.form['register_entry'])
    )
    db.add(disb)
    db.query(Payment).get(payment_id).status = PaymentStatus.DISBURSED
    db.commit()
    flash('Payment disbursed.', 'success')
    return redirect(url_for('view_payment', payment_id=payment_id))

@app.route('/payments/<int:payment_id>/bank-receipt', methods=['POST'])
@login_required
@role_required(['ACCOUNTS_OFFICER'])
def record_bank_receipt(payment_id):
    db = get_db()
    disb = db.query(Disbursement).filter_by(payment_id=payment_id).first()
    disb.bank_receipt_recorded = True
    db.query(Payment).get(payment_id).status = PaymentStatus.COMPLETED
    db.commit()
    flash('Bank receipt recorded.', 'success')
    return redirect(url_for('view_payment', payment_id=payment_id))

@app.route('/reconciliation')
@login_required
@role_required(['ACCOUNTS_OFFICER', 'FINANCE_OFFICER'])
def reconciliation():
    db = get_db()
    recons = db.query(Reconciliation).order_by(Reconciliation.year.desc(), Reconciliation.month.desc()).all()
    return render_template('reconciliation.html', reconciliations=recons)

@app.route('/reconciliation/new', methods=['GET', 'POST'])
@login_required
@role_required(['ACCOUNTS_OFFICER'])
def new_reconciliation():
    if request.method == 'POST':
        db = get_db()
        recon = Reconciliation(
            reconciliation_id=f"RECON-{request.form['year']}-{request.form['month']}-{str(uuid.uuid4())[:6]}",
            month=request.form['month'],
            year=int(request.form['year']),
            opening_bank_balance=float(request.form['opening_balance']),
            closing_bank_balance=float(request.form['closing_balance'])
        )
        db.add(recon)
        db.commit()
        flash('Reconciliation recorded.', 'success')
        return redirect(url_for('reconciliation'))
    return render_template('new_reconciliation.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
