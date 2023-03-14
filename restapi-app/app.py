from flask import Flask, jsonify, render_template, redirect, request, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import and_, text
import uuid
from functools import wraps
import hmac
import hashlib
import random
import datetime
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import jwt

app = Flask(__name__)

# Used for any other security related needs by extensions or application, i.e. csrf token
app.config['SECRET_KEY'] = 'mysecretkey'
# Required for cookies set by Flask to work in the preview window that's integrated in the lab IDE
app.config['SESSION_COOKIE_SAMESITE'] = 'None'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = True
# Initialize database
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///carcatalog.db"
# API security
app.config["HMAC_SECRET_KEY"] = "pythonapisecurekey"
app.config["BASIC_SECRET_KEY"] = "basicauthkey"
app.config["JWT_SECRET_KEY"] = "pythonjwtsecretkey"

db = SQLAlchemy(app)

limiter = Limiter(get_remote_address, app=app, default_limits=["200 per day", "50 per hour"],
                  storage_uri="memory://", )


# Model class
class Car(db.Model):
    id = db.Column(db.String(50), primary_key=True)
    brand = db.Column(db.String(50))
    model = db.Column(db.String(50))
    transmission = db.Column(db.String(20))
    price = db.Column(db.Integer)
    release_year = db.Column(db.Integer)
    created_at = db.Column(db.DateTime)

    def __init__(self, id, brand, model, transmission, price, release_year):
        self.id = id
        self.brand = brand
        self.model = model
        self.transmission = transmission
        self.price = price
        self.release_year = release_year
        self.created_at = datetime.datetime.utcnow()

    def as_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


with app.app_context():
    db.drop_all()
    db.create_all()

    for i in range(1, 101):
        if i <= 33:
            brand = 'Honda'
        elif i <= 66:
            brand = 'Ford'
        else:
            brand = 'BMW'

        model = brand + ' ' + str(i)

        if i % 2 != 0:
            transmission = 'AUTOMATIC'
        else:
            transmission = 'MANUAL'

        price = random.randint(30000, 80000)
        release_year = 2020 + (i % 3)
        car = Car(str(uuid.uuid4()), brand, model, transmission, price, release_year)
        db.session.add(car)
        db.session.commit()


def token_validator(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None

        if 'api-jwt' in request.headers:
            token = request.headers['api-jwt']
        if not token:
            return jsonify({'message': 'Token is missing!'}), 401
        try:
            is_valid_jwt = jwt.decode(token, app.config['JWT_SECRET_KEY'], 'HS256')
        except:
            return jsonify({'message': 'Token is invalid'}), 401
        return f(is_valid_jwt, *args, **kwargs)

    return decorated


@app.route("/")
def index():
    print('Received headers', request.headers)
    return render_template('base.html')


@app.route("/redirect/")
def redirect_to_index():
    return redirect(url_for('index'))


@app.route('/api/auth', methods=['POST'])
def login():
    auth = request.authorization
    if not auth or not auth.username or not auth.password:
        response = {'message': 'Missing authorization properties'}
        return jsonify(response), 401

    # candidate = Candidate.query.filter_by(email=auth.username).first()
    #
    # if not candidate:
    #     return jsonify({'message': 'Could not verify'}), 401

    if auth.password == app.config['BASIC_SECRET_KEY'] and auth.username == "Purvesh":
        token = jwt.encode({
            'iss': auth.username, 'sub': 'headhunter-candidate',
            'exp': datetime.datetime.utcnow() + datetime.timedelta(minutes=5)
        }, app.config['JWT_SECRET_KEY'], 'HS256')
        response = {'token': token}
        return jsonify(response), 200

    response = {'message': 'Could not verify'}
    return jsonify(response), 401


# Get cars
@app.route('/api/cars', methods=['GET'])
def find_cars():
    # Query parameters from the API
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 10, type=int)
    brand = request.args.get('brand', '%')
    model = request.args.get('model', '%')
    transmission = request.args.get('transmission', '%')
    price_operator = request.args.get('price_operator')
    price_value = request.args.get('price', 0, type=int)
    price_max_value = request.args.get('price_max', price_value + 1, type=int)
    sort_by = request.args.get('sort_by')
    sort_direction = request.args.get('sort_direction')

    query = Car.query

    query = query.filter(
        and_(
            Car.brand.ilike(f"%{brand}%"),
            Car.model.ilike(f"%{model}%"),
            Car.transmission.ilike(f"%{transmission}%")
        )
    )

    if price_operator == 'lte':
        query = query.filter(Car.price <= price_value)
    elif price_operator == 'gte':
        query = query.filter(Car.price >= price_value)
    elif price_operator == 'between':
        query = query.filter(Car.price >= price_value, Car.price <= price_max_value)

    # Sort functionality
    if sort_by:
        list_sort_by = sort_by.split(',')
        list_sort_direction = sort_direction.split(',') if sort_direction else []

        diff = len(list_sort_by) - len(list_sort_direction)

        for x in range(diff):
            list_sort_direction.append('asc')

        sort_columns = []

        for idx, sb in enumerate(list_sort_by):
            sort_columns.append(sb + ' ' + list_sort_direction[idx])

        query = query.order_by(text(','.join(sort_columns)))

        if sort_by and sort_direction == 'asc':
            query = query.order_by(getattr(Car, sort_by).asc())
        elif sort_by and sort_direction == 'desc':
            query = query.order_by(getattr(Car, sort_by).desc())

    cars = query.paginate(page=page, per_page=size)

    cars_response = [car.as_dict() for car in cars.items]

    return jsonify(
        data=cars_response,
        page=page,
        size=size,
        total_element=cars.total,
        total_page=cars.pages
    ), 200


def hmac_validator(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        client_hmac = None
        if 'api-signature' in request.headers:
            client_hmac = request.headers['api-signature']
        if not client_hmac:
            return jsonify({'messages': 'Missing headers api-signature'}), 401
        try:
            data = request.get_json()
            messages = str(
                request.method + '-' +
                request.path.lstrip('/') + '-' +
                data['brand'] + '-' +
                data['model'] + '-' +
                str(data['price']) + '-' +
                str(data['release_year']) + '-' +
                data['transmission']
            ).lower()
            hmac_verifier = hmac.new(app.config['HMAC_SECRET_KEY'].encode('utf-8'), messages.encode('utf-8'),
                                     hashlib.sha256)
            is_verified = hmac.compare_digest(request.headers['api-signature'], hmac_verifier.hexdigest())
        except:
            return jsonify({'message': 'Invalid api-signature'}), 400
        return f(is_verified, *args, **kwargs)

    return decorated


# Get car
@app.route('/api/car/<car_id>', methods=['GET'])
@limiter.limit("5/minute")
@token_validator
def get_car(is_valid_jwt, car_id):
    # car_id = request.args.get('id', type=str)
    if not is_valid_jwt:
        return jsonify(is_valid_jwt), 401
    car = Car.query.filter_by(id=car_id).first()
    if not car:
        response = {
            "message": "Car with this ID not found!"
        }
        return jsonify(response), 404

    response = car.as_dict()
    return jsonify(response), 200


@app.route('/api/car', methods=['POST'])
@limiter.limit("5/minute")
@hmac_validator
def create_car(is_verified):
    if not is_verified:
        response = {'message': 'Invalid api-signature'}
        return jsonify(response), 400

    data = request.get_json()
    car_id = str(uuid.uuid4())
    car = Car(
        car_id,
        data.get("brand"),
        data.get("model"),
        data.get("transmission"),
        data.get("price"),
        data.get("release_year"),
    )
    db.session.add(car)
    db.session.commit()
    response = {
        "car_id": car_id
    }
    return jsonify(response), 201


# Add car


if __name__ == "__main__":
    app.run()
