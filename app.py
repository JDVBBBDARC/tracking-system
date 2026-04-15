from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from models import db, Driver, LocationLog
from datetime import datetime, timedelta
import re
import os

app = Flask(__name__)
app.secret_key = 'tracking-secret-2025'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///tracking.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def validate_ph_phone(phone):
    """Validate Philippine mobile number (09XXXXXXXXX, 11 digits)."""
    phone = phone.strip().replace('-', '').replace(' ', '')
    pattern = r'^09\d{9}$'
    return re.match(pattern, phone) is not None, phone


def get_network(phone):
    """Return the PH network name from the phone prefix."""
    prefix = phone[:4]
    globe = ['0817', '0904', '0905', '0906', '0915', '0916', '0917', '0926',
             '0927', '0935', '0936', '0937', '0945', '0953', '0954', '0955',
             '0956', '0965', '0966', '0967', '0975', '0976', '0977', '0978',
             '0979', '0995', '0996', '0997']
    smart = ['0908', '0911', '0912', '0913', '0914', '0918', '0919', '0920',
             '0921', '0928', '0929', '0930', '0938', '0939', '0946', '0947',
             '0948', '0949', '0950', '0951', '0961', '0962', '0963', '0968',
             '0969', '0970', '0981', '0989', '0998', '0999']
    dito   = ['0895', '0896', '0897', '0898']
    if prefix in globe:
        return 'Globe'
    if prefix in smart:
        return 'Smart/TNT'
    if prefix in dito:
        return 'DITO'
    return 'Unknown'


# ---------------------------------------------------------------------------
# Admin pages
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    drivers = Driver.query.filter_by(is_active=True).all()
    return render_template('index.html', drivers=drivers)


@app.route('/drivers')
def drivers():
    all_drivers = Driver.query.order_by(Driver.created_at.desc()).all()
    return render_template('drivers.html', drivers=all_drivers)


@app.route('/drivers/add', methods=['POST'])
def add_driver():
    name    = request.form.get('name', '').strip()
    phone   = request.form.get('phone', '').strip()
    vehicle = request.form.get('vehicle', '').strip()

    if not name or not phone:
        flash('Name and phone number are required.', 'error')
        return redirect(url_for('drivers'))

    valid, phone = validate_ph_phone(phone)
    if not valid:
        flash('Invalid PH phone number. Format: 09XXXXXXXXX (11 digits).', 'error')
        return redirect(url_for('drivers'))

    existing = Driver.query.filter_by(phone=phone).first()
    if existing:
        flash(f'Phone number {phone} is already registered.', 'error')
        return redirect(url_for('drivers'))

    driver = Driver(name=name, phone=phone, vehicle=vehicle)
    db.session.add(driver)
    db.session.commit()
    flash(f'Driver {name} added successfully.', 'success')
    return redirect(url_for('drivers'))


@app.route('/drivers/toggle/<int:driver_id>', methods=['POST'])
def toggle_driver(driver_id):
    driver = Driver.query.get_or_404(driver_id)
    driver.is_active = not driver.is_active
    db.session.commit()
    status = 'activated' if driver.is_active else 'deactivated'
    flash(f'Driver {driver.name} {status}.', 'success')
    return redirect(url_for('drivers'))


@app.route('/drivers/delete/<int:driver_id>', methods=['POST'])
def delete_driver(driver_id):
    driver = Driver.query.get_or_404(driver_id)
    LocationLog.query.filter_by(phone=driver.phone).delete()
    db.session.delete(driver)
    db.session.commit()
    flash(f'Driver {driver.name} deleted.', 'success')
    return redirect(url_for('drivers'))


@app.route('/history/<phone>')
def history(phone):
    driver = Driver.query.filter_by(phone=phone).first_or_404()
    logs = (LocationLog.query
            .filter_by(phone=phone)
            .order_by(LocationLog.timestamp.desc())
            .limit(100)
            .all())
    return render_template('history.html', driver=driver, logs=logs)


# ---------------------------------------------------------------------------
# Mobile tracking page (driver opens this on their phone)
# ---------------------------------------------------------------------------

@app.route('/track/<phone>')
def track(phone):
    driver = Driver.query.filter_by(phone=phone, is_active=True).first()
    if not driver:
        return render_template('track_error.html', phone=phone), 404
    network = get_network(phone)
    return render_template('track.html', driver=driver, network=network)


# ---------------------------------------------------------------------------
# REST API
# ---------------------------------------------------------------------------

@app.route('/api/location/update', methods=['POST'])
def api_location_update():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'No data received'}), 400

    phone = data.get('phone', '').strip()
    lat   = data.get('latitude')
    lng   = data.get('longitude')

    if not phone or lat is None or lng is None:
        return jsonify({'error': 'phone, latitude, and longitude are required'}), 400

    valid, phone = validate_ph_phone(phone)
    if not valid:
        return jsonify({'error': 'Invalid PH phone number'}), 400

    driver = Driver.query.filter_by(phone=phone, is_active=True).first()
    if not driver:
        return jsonify({'error': 'Driver not found or inactive'}), 404

    log = LocationLog(
        phone=phone,
        driver_name=driver.name,
        latitude=float(lat),
        longitude=float(lng),
        accuracy=data.get('accuracy'),
        speed=data.get('speed'),
        heading=data.get('heading'),
        is_tracking=True
    )
    db.session.add(log)
    db.session.commit()

    return jsonify({'status': 'ok', 'message': 'Location saved'})


@app.route('/api/location/stop', methods=['POST'])
def api_location_stop():
    data = request.get_json(silent=True) or {}
    phone = data.get('phone', '').strip()

    valid, phone = validate_ph_phone(phone)
    if not valid:
        return jsonify({'error': 'Invalid phone'}), 400

    # Mark last log as stopped
    last_log = (LocationLog.query
                .filter_by(phone=phone)
                .order_by(LocationLog.timestamp.desc())
                .first())
    if last_log:
        last_log.is_tracking = False
        db.session.commit()

    return jsonify({'status': 'ok', 'message': 'Tracking stopped'})


@app.route('/api/location/all')
def api_location_all():
    """
    Return the latest location for each active driver.
    Drivers with no update in the last 2 minutes are considered offline.
    """
    cutoff = datetime.utcnow() - timedelta(minutes=2)
    drivers = Driver.query.filter_by(is_active=True).all()

    result = []
    for driver in drivers:
        latest = (LocationLog.query
                  .filter_by(phone=driver.phone)
                  .order_by(LocationLog.timestamp.desc())
                  .first())

        if latest:
            data = latest.to_dict()
            data['online'] = latest.timestamp >= cutoff and latest.is_tracking
            data['vehicle'] = driver.vehicle or ''
        else:
            data = {
                'phone':       driver.phone,
                'driver_name': driver.name,
                'vehicle':     driver.vehicle or '',
                'latitude':    None,
                'longitude':   None,
                'online':      False,
                'timestamp':   None
            }
        result.append(data)

    return jsonify(result)


@app.route('/api/location/history/<phone>')
def api_location_history(phone):
    """Return last 50 location points for a driver (for trail drawing)."""
    valid, phone = validate_ph_phone(phone)
    if not valid:
        return jsonify({'error': 'Invalid phone'}), 400

    logs = (LocationLog.query
            .filter_by(phone=phone)
            .order_by(LocationLog.timestamp.desc())
            .limit(50)
            .all())
    return jsonify([l.to_dict() for l in logs])


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0', port=5000)
