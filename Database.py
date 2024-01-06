from sqlalchemy import create_engine, Column, DateTime, Integer, Boolean, Text, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from sqlalchemy import and_
from datetime import datetime, timedelta


Base = declarative_base()

class Guild(Base):
    __tablename__ = 'guilds'

    id = Column(Integer, primary_key=True, autoincrement=True)
    guildid = Column(Integer, unique=True)
    guildname = Column(Text)
    enforce = Column(Integer, default=0)
    auditlogchannel = Column(Integer, default=0)

class Ban(Base):
    __tablename__ = 'bans'

    id = Column(Integer, primary_key=True, autoincrement=True)
    userid = Column(Integer)
    guildid = Column(Integer, ForeignKey('guilds.id'))
    reason = Column(Text)
    when = Column(DateTime, default=datetime.utcnow())
    issuedby = Column(Integer)
    expires = Column(Boolean, default=True)
    expiresby = Column(DateTime, default=datetime.utcnow() + timedelta(days=7))
    banned = Column(Boolean, default=True)
    actioned = Column(Boolean, default=False)
    guild = relationship('Guild', backref='bans')

    @property
    def active(self):
        return True if self.expiresby > datetime.utcnow() else False

    @property
    def outstanding(self):
        return True if not self.actioned and self.banned == True else False

    @property
    def expired(self):
        return True if self.active and self.banned else False

class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, autoincrement=True)
    userid = Column(Integer, unique=True)
    userip = Column(Text)
    
class Verification(Base):
    __tablename__ = "verifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    userid = Column(Integer, unique=True)
    code = Column(Text, unique=True)

# Replace 'sqlite:///example.db' with the actual database URL you want to use
engine = create_engine('sqlite:///Vanguard.sqlite')
Base.metadata.create_all(engine)

Session = sessionmaker(bind=engine)
session = Session()