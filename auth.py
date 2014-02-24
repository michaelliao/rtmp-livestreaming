#!/usr/bin/env python
# -*- coding: utf-8 -*-

__author__ = 'Michael Liao'

' Auth module '

import os, re, time, base64, hashlib, logging, functools

try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO

from transwarp.web import ctx, view, get, post, route, jsonrpc, Dict, Template, seeother, notfound, badrequest
from transwarp import db, i18n

_REG_EMAIL = re.compile(r'^[0-9a-z]([\-\.\w]*[0-9a-z])*\@([0-9a-z][\-\w]*[0-9a-z]\.)+[a-z]{2,9}$')

_SESSION_COOKIE_NAME = '_auth_session_cookie'
_SESSION_COOKIE_SALT = '_iTransWARP-SALT_'
_SESSION_COOKIE_EXPIRES = 31536000.0
_COOKIE_SIGNIN_REDIRECT = '_auth_redirect_'

@get('/auth/signin')
@view('templates/auth/signin.html')
def signin():
    redirect = ctx.request.get('redirect', '')
    if not redirect:
        redirect = ctx.request.header('REFERER')
    if not redirect or redirect.find('/signin')!=(-1):
        redirect = '/'
    ctx.response.set_cookie(_COOKIE_SIGNIN_REDIRECT, redirect)
    return dict(__site_name__='FIXME')

@post('/auth/signin')
@view('templates/auth/signin.html')
def do_signin():
    i = ctx.request.input(remember='')
    email = i.email.strip().lower()
    passwd = i.passwd
    remember = i.remember
    if not email or not passwd:
        return dict(email=email, remember=remember, error=_('Bad email or password'))
    us = db.select('select id, passwd from users where email=?', email)
    if not us:
        return dict(email=email, remember=remember, error=_('Bad email or password'))
    u = us[0]
    if passwd != u.passwd:
        logging.debug('expected passwd: %s' % u.passwd)
        return dict(email=email, remember=remember, error=_('Bad email or password'))
    expires = time.time() + _SESSION_COOKIE_EXPIRES if remember else None
    make_session_cookie(u.id, passwd, expires)
    ctx.response.delete_cookie(_COOKIE_SIGNIN_REDIRECT)
    raise seeother(ctx.request.cookie(_COOKIE_SIGNIN_REDIRECT, '/'))

@get('/auth/signout')
def signout():
    delete_session_cookie()
    redirect = ctx.request.get('redirect', '')
    if not redirect:
        redirect = ctx.request.header('REFERER', '')
    if not redirect or redirect.find('/admin/')!=(-1) or redirect.find('/signin')!=(-1):
        redirect = '/'
    logging.debug('signed out and redirect to: %s' % redirect)
    raise seeother(redirect)

def http_basic_auth(auth):
    try:
        s = base64.b64decode(auth)
        logging.warn(s)
        u, p = s.split(':', 1)
        user = db.select_one('select * from users where email=?', u)
        if user.passwd==hashlib.md5(p).hexdigest():
            logging.info('Basic auth ok: %s' % u)
            return user
        return None
    except BaseException, e:
        logging.exception('auth failed.')
        return None

def make_session_cookie(uid, passwd, expires):
    '''
    Generate a secure client session cookie by constructing: 
    base64(uid, expires, md5(uid, expires, passwd, salt)).
    
    Args:
        uid: user id.
        expires: unix-timestamp as float.
        passwd: user's password.
        salt: a secure string.
    Returns:
        base64 encoded cookie value as str.
    '''
    sid = str(uid)
    exp = str(int(expires)) if expires else str(int(time.time() + 86400))
    secure = ':'.join([sid, exp, str(passwd), _SESSION_COOKIE_SALT])
    cvalue = ':'.join([sid, exp, hashlib.md5(secure).hexdigest()])
    logging.info('make cookie: %s' % cvalue)
    cookie = base64.urlsafe_b64encode(cvalue).replace('=', '_')
    ctx.response.set_cookie(_SESSION_COOKIE_NAME, cookie, expires=expires)

def extract_session_cookie():
    '''
    Decode a secure client session cookie and return uid, or None if invalid cookie.

    Returns:
        user id as str, or None if cookie is invalid.
    '''
    try:
        s = str(ctx.request.cookie(_SESSION_COOKIE_NAME, ''))
        logging.debug('read cookie: %s' % s)
        if not s:
            return None
        ss = base64.urlsafe_b64decode(s.replace('_', '=')).split(':')
        if len(ss)!=3:
            raise ValueError('bad cookie: %s' % s)
        uid, exp, md5 = ss
        if float(exp) < time.time():
            raise ValueError('expired cookie: %s' % s)
        expected_pwd = str(db.select_one('select passwd from users where id=?', userid).passwd)
        expected = ':'.join([uid, exp, expected_pwd, _SESSION_COOKIE_SALT])
        if hashlib.md5(expected).hexdigest()!=md5:
            raise ValueError('bad cookie: unexpected md5.')
        return uid
    except BaseException, e:
        logging.debug('something wrong when extract cookie: %s' % e.message)
        delete_session_cookie()
        return None

def delete_session_cookie():
    ' delete the session cookie immediately. '
    logging.debug('delete session cookie.')
    ctx.response.delete_cookie(_SESSION_COOKIE_NAME)

def load_user(func):
    @functools.wraps(func)
    def _wrapper(*args, **kw):
        user = None
        uid = extract_session_cookie()
        if uid:
            users = db.select('select * from users where id=?', uid)
            if users:
                user = users[0]
                logging.info('load user ok from cookie.')
        if user is None:
            auth = ctx.request.header('AUTHORIZATION')
            logging.debug('get authorization header: %s' % auth)
            if auth and auth.startswith('Basic '):
                user = http_basic_auth(auth[6:])
        ctx.user = user
        try:
            return func(*args, **kw)
        finally:
            del ctx.user
    return _wrapper

def load_i18n(func):
    @functools.wraps(func)
    def _wrapper(*args, **kw):
        lc = 'en'
        al = ctx.request.header('ACCEPT-LANGUAGE')
        if al:
            lcs = al.split(',')
            lc = lcs[0].strip().lower()
        with i18n.locale(lc):
            return func(*args, **kw)
    return _wrapper
