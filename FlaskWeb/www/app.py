# coding=utf-8
import sys
sys.path.append('..')
import config
import Models
from datetime import date, datetime,time
import json
import datetime
from Models import User
import DBhandler as dbs
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import scoped_session
from sqlalchemy import create_engine
from flask_cors import CORS
from flask import Flask, render_template, request, jsonify, send_from_directory,redirect, url_for, Response
from database import init_db,db_session
from Models import User

init_db()
app = Flask(__name__ ,template_folder='templates',static_folder='', static_url_path='')
CORS(app)

#====================================创建引擎===================================
engine = create_engine(config.MYSQL_SERVER_URI, encoding='utf8', max_overflow=5)
session_factory = sessionmaker(bind=engine)
session = scoped_session(session_factory)

#====================================创建表单===================================
Models.Base.metadata.create_all(engine)


class DateEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime.datetime):
            return obj.strftime('%Y-%m-%d %H:%M:%S')
        elif isinstance(obj, date):
            return obj.strftime("%Y-%m-%d")
        elif isinstance(obj,time):
            return obj.strftime("%H:%M:%S")
        else:
            return json.JSONEncoder.default(self, obj)
@app.route('/',methods=['GET'])
def loginIndex():
    return render_template('login.html')

@app.route('/aicyber/resource')
def index2():
    return render_template('Tables.html')

@app.route('/aicyber/resource/login',methods=['POST'])
def login():
    name = request.form.get('username')
    pwd = request.form.get('password')
    user = session.query(User).filter_by( username = name).first()
    print user
    if user != None:
        print user.username
        print user.confirm_password(pwd)
        if user.confirm_password(pwd):
            print '----------confirm_password------------',user.confirm_password(pwd)
            return redirect(url_for('index2'))

    return redirect(url_for('loginIndex'))

@app.route('/aicyber/resource/api',methods=['POST'])
def run_sql_string():
    data = None
    print request.json
    if not request.json:
        return jsonify({'successful':False, 'message':'请求的数据格式不正确'})
    if request.method == 'POST':
        json_sqlString = request.json['sql_string']
        json_flg = request.json['flg']
        if json_flg == 'select_one':
            datas = dbs.get_one_sql(json_sqlString)
        elif json_flg == 'select_all':
            data = dbs.get_all_sql(json_sqlString)
            print 'data====',data
            datas =  json.dumps(data, cls=DateEncoder)
        elif json_flg == 'update':
            dbs.update_sql(json_sqlString)
        return Response(
            response=datas,
            mimetype="application/json",
            status=200)
        # return jsonify({'success': True, 'message': u'成功响应', 'data': datas})
    else:
        return jsonify({'success': False, 'message': u'请使用POST请求', 'data': None})





if __name__ == '__main__':
    # app.run(host="0.0.0.0",port=int("8081"),debug=True)
    # u = session.query(User).filter_by(username = 'admin').first().delete()
    # print u
    # u2 = session.query(User.id==27).one()
    # print u2
    u  = User('admin123','aicyber_ubuntu330M.')
    print u.getPassWord_hash()
    u = session.query(User).filter_by(username='admin123').update({'username':'admin1','password_hash':u.getPassWord_hash()})
    print '--*-*- ',u
    session.commit()

    # u = User('admin1', '123')
    # session.add(u)
    # session.commit()
    # print u.generate_token()
    # db_session.add(u)
    # db_session.commit()
    # print Session.query(User).all()
    # ss = Session.query(User).filter_by(id=1).first()
    # print ss
