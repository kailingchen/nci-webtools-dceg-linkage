#!/usr/bin/env python

import sqlite3
import json
import os.path
import binascii
import yaml

import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import datetime


# Set data directories using config.yml
with open('config.yml', 'r') as f:
    config = yaml.load(f)
api_users_dir = config['api']['api_users_dir']
token_expiration = bool(config['api']['token_expiration'])
token_expiration_days = config['api']['token_expiration_days']

# email user token
def emailUser(email, token, expiration, firstname):
    print "sending message"
    packet = MIMEMultipart()
    packet['Subject'] = "LDLink API Access Token"
    # packet['From'] = "LDlink" + " <do.not.reply@nih.gov>"
    packet['From'] = "NCI LDlink Web Admin" + " <NCILDlinkWebAdmin@mail.nih.gov>"
    packet['To'] = email
    message = ''
    if token_expiration:
        message = 'Dear ' + firstname + ', ' + '<br><br>' + 'Thank you for registering to use the LDlink API. <br><br>' + 'Token: ' + token + '<br>' + 'Your token expires on: ' + expiration + '<br><br>' + 'Please include this token as an argument in your request. Examples are listed in the <a href="https://ldlink.nci.nih.gov/?tab=apiaccess"><u>API Access</u></a> tab. <br><br>' + 'LDlink Web Admin'
    else:
        message = 'Dear ' + firstname + ', ' + '<br><br>' + 'Thank you for registering to use the LDlink API. <br><br>' + 'Token: ' + token + '<br><br>' + 'Please include this token as an argument in your request. Examples are listed in the <a href="https://ldlink.nci.nih.gov/?tab=apiaccess"><u>API Access</u></a> tab. <br><br>' + 'LDlink Web Admin'

    packet.attach(MIMEText(message, 'html'))

    # print self.MAIL_HOST
    # temp use localhost, use official NIH mailfwd account in future (put in config file)
    smtp = smtplib.SMTP("localhost")
    # smtp.sendmail("do.not.reply@nih.gov", email, packet.as_string())
    smtp.sendmail("NCILDlinkWebAdmin@mail.nih.gov", email, packet.as_string())

# creates table in database if database did not exist before
def createTable(api_users_dir):
    # create database
    con = sqlite3.connect(api_users_dir + 'api_users.db')
    con.text_factory = str
    cur = con.cursor()
    cur.execute(
        "CREATE TABLE api_users (`first_name` TEXT, `last_name` TEXT, `email` TEXT, `institution` TEXT, `token` TEXT, `registered` DATETIME);")
    con.commit()
    con.close()

# check if user email record exists
def getEmailRecord(curr, email):
    temp = (email,)
    curr.execute("SELECT * FROM api_users WHERE email=?", temp)
    return curr.fetchone()

def insertRecord(firstname, lastname, email, institution, token, registered):
    con = sqlite3.connect(api_users_dir + 'api_users.db')
    con.text_factory = str
    cur = con.cursor()
    cur.execute(
        "CREATE TABLE IF NOT EXISTS api_users (`first_name` TEXT, `last_name` TEXT, `email` TEXT, `institution` TEXT, `token` TEXT, `registered` DATETIME);")
    con.commit()
    temp = (firstname, lastname, email, institution, token, registered)
    cur.execute(
        "INSERT INTO api_users (first_name, last_name, email, institution, token, registered) VALUES (?,?,?,?,?,?)", temp)
    con.commit()
    con.close()

# update record only if email's token is expired and user re-registers
def updateRecord(firstname, lastname, email, institution, token, registered):
    con = sqlite3.connect(api_users_dir + 'api_users.db')
    con.text_factory = str
    cur = con.cursor()
    temp = (firstname, lastname, institution, token, registered, email)
    cur.execute(
        "UPDATE api_users SET first_name=?, last_name=?, institution=?, token=?, registered=? WHERE email=?", temp)
    con.commit()
    con.close()

# check if token is already in db
def checkUniqueToken(curr, token):
    temp = (token,)
    curr.execute("SELECT * FROM api_users WHERE token=?", temp)
    if curr.fetchone() is None:
        return False
    else:
        return True

# check if token is valid when hitting API route and not expired
def checkToken(token):
    con = sqlite3.connect(api_users_dir + 'api_users.db')
    con.text_factory = str
    cur = con.cursor()
    cur.execute(
        "CREATE TABLE IF NOT EXISTS api_users (`first_name` TEXT, `last_name` TEXT, `email` TEXT, `institution` TEXT, `token` TEXT, `registered` DATETIME);")
    con.commit()
    temp = (token,)
    cur.execute("SELECT * FROM api_users WHERE token=?", temp)
    record = cur.fetchone()
    con.close()
    if record is None:
        return False
    else:
        # return True
        present = getDatetime()
        registered = datetime.datetime.strptime(record[5], "%Y-%m-%d %H:%M:%S")
        expiration = getExpiration(registered)
        if ((present < expiration) or not token_expiration):
            return True
        else:
            return False

# generate unique access token for each user
def generateToken(curr):
    token = binascii.b2a_hex(os.urandom(6))
    # if true, generate another token - make sure example token is not generated
    while(checkUniqueToken(curr, token) or token == "faketoken123"):
        token = binascii.b2a_hex(os.urandom(6))
    return token

# get current date and time
def getDatetime():
    return datetime.datetime.now()

# get current date and time
def getExpiration(registered):
    return registered + datetime.timedelta(minutes=5)
    # return registered + datetime.timedelta(days=token_expiration_days)

# registers new users and emails generated token for WEB
def register_user_web(firstname, lastname, email, institution, reference):
    out_json = {}

    # create database and table if it does not exist already
    if not os.path.exists(api_users_dir + 'api_users.db'):
        print "api_usrs.db created."
        createTable(api_users_dir)

    # Connect to snp database
    conn = sqlite3.connect(api_users_dir + 'api_users.db')
    conn.text_factory = str
    curr = conn.cursor()

    record = getEmailRecord(curr, email)
    print record
    # if email record exists, do not insert to db
    if record != None:
        present = getDatetime()
        registered = datetime.datetime.strptime(record[5], "%Y-%m-%d %H:%M:%S")
        expiration = getExpiration(registered)
        format_expiration = expiration.strftime("%Y-%m-%d %H:%M:%S")
        if ((present < expiration) or not token_expiration):
            out_json = {
                "message": "Email already registered.",
                "firstname": record[0],
                "lastname": record[1],
                "email": record[2],
                "institution": record[3],
                "token": record[4],
                "registered": record[5]
            }
            emailUser(record[2], record[4], format_expiration, record[0])
        else:
            token = generateToken(curr)
            registered = getDatetime()
            expiration = getExpiration(registered)
            format_registered = registered.strftime("%Y-%m-%d %H:%M:%S")
            format_expiration = expiration.strftime("%Y-%m-%d %H:%M:%S")
            updateRecord(firstname, lastname, email, institution, token, format_registered)
            out_json = {
                "message": "Thank you for registering to use the LDlink API.",
                "firstname": firstname,
                "lastname": lastname,
                "email": email,
                "institution": institution,
                "token": token,
                "registered": format_registered
            }
            emailUser(email, token, format_expiration, firstname)
    else:
        # if email record does not exists in db, add to table
        token = generateToken(curr)
        registered = getDatetime()
        expiration = getExpiration(registered)
        format_registered = registered.strftime("%Y-%m-%d %H:%M:%S")
        format_expiration = expiration.strftime("%Y-%m-%d %H:%M:%S")
        insertRecord(firstname, lastname, email, institution, token, format_registered)
        out_json = {
            "message": "Thank you for registering to use the LDlink API.",
            "firstname": firstname,
            "lastname": lastname,
            "email": email,
            "institution": institution,
            "token": token,
            "registered": format_registered
        }
        emailUser(email, token, format_expiration, firstname)

    conn.close()
    return out_json

# registers new users and emails generated token for API
def register_user_api(firstname, lastname, email, institution, token, registered):
    out_json = {}

    # create database and table if it does not exist already
    if not os.path.exists(api_users_dir + 'api_users.db'):
        print "api_usrs.db created."
        createTable(api_users_dir)

    # Connect to snp database
    conn = sqlite3.connect(api_users_dir + 'api_users.db')
    conn.text_factory = str
    curr = conn.cursor()

    record = getEmailRecord(curr, email)

    # if email record exists, do not insert to db
    if record != None:
        # if email record in api database does not have new token, update it
        if (record[2] == email and record[4] != token):
            updateRecord(firstname, lastname, email, institution, token, registered)
            out_json = {
                "message": "Thank you for registering to use the LDlink API.",
                "firstname": firstname,
                "lastname": lastname,
                "email": email,
                "institution": institution,
                "token": token,
                "registered": registered
            }
        else:
            out_json = {
                "message": "Email already registered.",
                "firstname": record[0],
                "lastname": record[1],
                "email": record[2],
                "institution": record[3],
                "token": record[4],
                "registered": record[5]
            }
    else:
        # if email record does not exists in db, add to table
        insertRecord(firstname, lastname, email, institution, token, registered)
        out_json = {
            "message": "Thank you for registering to use the LDlink API.",
            "firstname": firstname,
            "lastname": lastname,
            "email": email,
            "institution": institution,
            "token": token,
            "registered": registered
        }

    conn.close()
    return out_json