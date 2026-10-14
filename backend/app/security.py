import os
from datetime import datetime,timedelta,timezone
from fastapi import Depends,HTTPException,status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt,JWTError
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User
ENVIRONMENT=os.getenv('ENVIRONMENT','development')
SECRET=os.getenv('JWT_SECRET') or ('healthtrace-local-development-secret-change-before-deployment' if ENVIRONMENT!='production' else '')
ALGORITHM='HS256';oauth=OAuth2PasswordBearer(tokenUrl='/api/auth/login');pwd=CryptContext(schemes=['bcrypt'],deprecated='auto')
def configured():
 if not SECRET: raise RuntimeError('JWT_SECRET must be configured in production')
def hash_password(password:str): return pwd.hash(password)
def verify(password:str,hashed:str): return pwd.verify(password,hashed)
def token(user:User):
 configured();return jwt.encode({'sub':str(user.id),'exp':datetime.now(timezone.utc)+timedelta(hours=8)},SECRET,algorithm=ALGORITHM)
def current_user(token_value:str=Depends(oauth),db:Session=Depends(get_db)):
 try: user_id=int(jwt.decode(token_value,SECRET,algorithms=[ALGORITHM])['sub'])
 except (JWTError,ValueError): raise HTTPException(status.HTTP_401_UNAUTHORIZED,'Invalid or expired session')
 user=db.get(User,user_id)
 if not user: raise HTTPException(status.HTTP_401_UNAUTHORIZED,'User not found')
 return user
