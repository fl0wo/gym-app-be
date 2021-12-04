import json
from flask import current_app, flash, jsonify, make_response, redirect, request, url_for
from flask_cors import CORS
from . import app, database
from .models import Cats, Users, Slots, Reservations, WeightRoomReservations
from .security import admin_required, get_current_user, get_current_admin, get_current_manager, is_logged
from .response import Response, DATE_FORMAT, DATE_FORMAT_IN, TIME_FORMAT
from werkzeug.security import generate_password_hash, \
    check_password_hash  # not constant due to salt adding (guarda rainbow table attack)
import uuid
import jwt
import datetime
from functools import wraps

from .controllers.user_controller import parse_me,\
    update_me,parse_my_res

CORS(app)

basicHeaders = [
    ('Content-Type', 'application/json'),
    ('Access-Control-Allow-Origin', '*'),
    ('Access-Control-Allow-Headers', 'Authorization, Content-Type'),
    ('Access-Control-Allow-Methods', 'POST'),
]


def sendResponse(payload, msg, status):
    r = Response()
    r.data = payload
    r.message = msg
    r.status = status
    return jsonify(r.toJSON()), status, basicHeaders


def doFinallyCatch(do, success, catch):
    try:
        do()
    except:
        return catch
    finally:
        return success


def ifLogged(f):
    user = get_current_user(request)
    if user is None:
        return jsonify({'message': 'user not logged'}), 401
    return f(user)


@app.route('/me', methods=['GET'])
def me():
    return ifLogged(lambda user:
                    sendResponse(parse_me(user), "", 200))


@app.route('/me', methods=['POST'])
def me_update():
    return ifLogged(lambda user:
                    doFinallyCatch(
                        update_me(user, request),
                        sendResponse({}, "Updated", 200),
                        sendResponse({}, "Error", 503)
                    ))


@app.route('/me/reservations', methods=['GET'])
def my_reservations():
    return ifLogged(lambda user:
                    sendResponse(parse_my_res(user), "", 200))


@app.route('/users', methods=['GET'])
def fetch():
    admin = get_current_admin(request)
    if admin is None:
        return jsonify({'message': 'user not logged'}), 401
    if admin is False:
        return jsonify({'message': 'role not sufficient'}), 401

    dbusers = database.get_all(Users)
    users = []
    for user in dbusers:
        users.append({
            "name": user.name,
            "surname": user.surname,
            "role": user.role,
            "email": user.email,
            "birth_date": user.birth_date.strftime(DATE_FORMAT),
            "fiscal_code": user.fiscal_code
        })
    return sendResponse(json.dumps(users), "", 200)


@app.route('/slots/reservations', methods=['GET'])
def fetchSlotsReservations():
    dbSlots = database.get_all_slots_curent_reservation()
    slots = []
    for s in dbSlots:
        slots.append({
            "id": s['id'],
            "date": (s['date']).strftime(DATE_FORMAT),
            "time_from": s['time_from'].strftime(TIME_FORMAT),
            "time_to": s['time_to'].strftime(TIME_FORMAT),
            "max_capacity": s['max_capacity'],
            "current_reservations": s['current_reservations'],
            "title": s['title'],
            "description": s['description']
        })
    return sendResponse(slots, "", 200)


@app.route('/lessons/reservations', methods=['GET'])
def fetchLessonsReservations():
    dbLessons = database.get_all_lessons_curent_reservation()
    lessons = []
    for l in dbLessons:
        lessons.append({
            "id": l['id'],
            "date": (l['date']).strftime(DATE_FORMAT),
            "time": l['time'].strftime(TIME_FORMAT),
            "max_participants": l['max_participants'],
            "current_reservations": l['current_reservations'],
            "course": l['course'],
            "course_description": l['course_description']
        })
    return sendResponse(lessons, "", 200)


@app.route('/slots/add', methods=['POST'])
def addSlot():
    manager = get_current_manager(request)
    if manager is None:
        return jsonify({'message': 'user not logged'}), 401
    if manager is False:
        return jsonify({'message': 'role not sufficient'}), 401

    body = request.get_json()
    # TODO: check that timefrom < timeto
    database.add_instance(Slots,
                          id=str(uuid.uuid4()),
                          date=body['date'],
                          time_from=body['time_from'],
                          time_to=body['time_to'],
                          max_capacity=body['max_capacity'],  # TODO: check if > 1
                          title=body['title'],
                          description=body['description'],
                          )

    return sendResponse({}, "Added", 200)


@app.route('/slots/reservation', methods=['POST'])
def addSlotReservation():
    user = get_current_user(request)
    if user is None:
        return jsonify({'message': 'user not logged'}), 401

    body = request.get_json()

    # database.begin_transaction() ---> sqlalchemy.exc.InvalidRequestError: A transaction is already begun on this Session.
    # TODO Cercare di capire come evitare sql injections, o facciamo dei controlli sul parametro oppure bisogna cambiare modo di fare le query
    db_is_space = database.check_if_space_for_slot_reservation(user.id)
    is_space = db_is_space[0]['there_is_space']  # TODO IVAN Controlla se sta roba funziona
    if is_space == 0:
        return sendResponse({}, "Not enough space in slot", 401)

    reservation_id = str(uuid.uuid4())
    database.add_instance_no_commit(Reservations,
                                    id=reservation_id,
                                    customer=body['idUser'],
                                    room='1')
    database.add_instance_no_commit(WeightRoomReservations,
                                    reservation_number=999,
                                    # FIXME TODO: MANDARGLI DA FRONT END/ fare query qui x prendersi il progressivo della reservation x quel determinato slot oppure eliminare il campo perche non viene mai usato
                                    reservation_id=reservation_id,
                                    slot=(body['idSlot']))
    database.commit_changes()

    return sendResponse({}, "Subscribed to slot", 200)


@app.route('/register', methods=['GET', 'POST'])
def signup_user():
    data = request.get_json()

    hashed_password = generate_password_hash(data['password'], method='sha256')

    try:
        database.add_instance(Users,
                              id=str(uuid.uuid4()),
                              email=data['email'],
                              password=hashed_password,
                              name=data['name'],
                              surname=data['surname'])
    except:
        return sendResponse({}, 'already registered', 200)

    return sendResponse({}, 'registered successfully', 200)


@app.route('/login', methods=['GET', 'POST'])
def login_user():
    auth = request.headers

    email = auth['username']
    try_password = auth['password']
    if not auth or not email or not try_password:
        return sendResponse({'Authentication': 'Basic realm: "login required"'}, 'could not verify', 401)

    user = database.get_by_email(Users, email)

    if check_password_hash(user.password, try_password):
        token = jwt.encode({
            'id': user.id,
            'exp': datetime.datetime.utcnow() + datetime.timedelta(minutes=30)},
            app.config['SECRET_KEY']
        )
        return sendResponse({'token': token.decode('UTF-8')}, "New token", 200)

    return sendResponse({'WWW.Authentication': 'Basic realm: "login required"'}, 'could not verify', 401)

# @app.route('/remove/<cat_id>', methods=['DELETE'])
# def remove(cat_id):
#     database.delete_instance(Cats, id=cat_id)
#     r = Response
#     r.message = json.dumps("Deleted")
#     return jsonify(r);


# @app.route('/edit/<cat_id>', methods=['PATCH'])
# def edit(cat_id):
#     data = request.get_json()
#     new_price = data['price']
#     database.edit_instance(Cats, id=cat_id, price=new_price)
#     r = Response
#     r.message = json.dumps("Edited")
#     return jsonify(r);
