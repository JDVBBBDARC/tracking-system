from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


class Driver(db.Model):
    __tablename__ = 'drivers'

    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(100), nullable=False)
    phone      = db.Column(db.String(15), unique=True, nullable=False)  # PH format: 09XXXXXXXXX
    vehicle    = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active  = db.Column(db.Boolean, default=True)

    def to_dict(self):
        return {
            'id':       self.id,
            'name':     self.name,
            'phone':    self.phone,
            'vehicle':  self.vehicle or '',
            'is_active': self.is_active,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M')
        }


class LocationLog(db.Model):
    __tablename__ = 'location_logs'

    id          = db.Column(db.Integer, primary_key=True)
    phone       = db.Column(db.String(15), nullable=False)
    driver_name = db.Column(db.String(100))
    latitude    = db.Column(db.Float, nullable=False)
    longitude   = db.Column(db.Float, nullable=False)
    accuracy    = db.Column(db.Float)
    speed       = db.Column(db.Float)        # meters per second
    heading     = db.Column(db.Float)        # degrees
    timestamp   = db.Column(db.DateTime, default=datetime.utcnow)
    is_tracking = db.Column(db.Boolean, default=True)  # False = driver stopped

    def to_dict(self):
        return {
            'id':          self.id,
            'phone':       self.phone,
            'driver_name': self.driver_name or self.phone,
            'latitude':    self.latitude,
            'longitude':   self.longitude,
            'accuracy':    self.accuracy,
            'speed':       round(self.speed * 3.6, 1) if self.speed else 0,  # convert to km/h
            'heading':     self.heading,
            'timestamp':   self.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            'is_tracking': self.is_tracking
        }
