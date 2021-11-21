import sqlalchemy
from . import config
from sqlalchemy.sql import text

from sqlalchemy import (create_engine, DDL)

engine = sqlalchemy.create_engine(config.DATABASE_CONNECTION_URI)


def define_schema(schema_name):
    engine.execute(DDL("CREATE SCHEMA IF NOT EXISTS " + schema_name))


def define_trigger():
    perform_query(open("src/example/triggers.sql"))


def define_roles():
    perform_query(open("src/example/roles.sql"))


def perform_query(file):
    query = text(file.read())
    engine.execute(query)
