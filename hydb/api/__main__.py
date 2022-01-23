from typing import List

from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy import and_

from ..db import DB

from .crud import models, schemas
from . import crud

app: FastAPI = FastAPI()
dbase: DB = DB()


@app.get("/")
def root():
    return {"message": "Hello, World!"}


@app.get("/hello/{name}")
def say_hello(name: str):
    return {"message": f"Hello {name}"}


@app.get("/server/info", response_model=schemas.ServerInfo)
def server_info():
    return crud.server_info(db=dbase)


@app.post("/u/", response_model=schemas.User)
def user_add(user_create: schemas.UserCreate, db: DB = Depends(dbase.yield_with_session)):
    db_user = crud.user_get_by_tgid(db, user_create.tg_user_id)

    if db_user:
        raise HTTPException(status_code=400, detail="Telegram ID already registered.")

    return crud.user_add(db=db, user_create=user_create)


@app.post("/u/{user_pk}")
def user_del(user_pk: int, user_delete: schemas.UserDelete, db: DB = Depends(dbase.yield_with_session)):
    db_user = crud.user_get_by_pkid(db, user_pk)

    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found.")

    if user_delete.tg_user_id != db_user.tg_user_id:
        raise HTTPException(status_code=403, detail="TG ID Mismatch.")

    db_user.delete(db)


@app.get("/u/{user_pk}", response_model=schemas.User)
def user_get(user_pk: int, db: DB = Depends(dbase.yield_with_session)):
    db_user = crud.user_get_by_pkid(db, user_pk)

    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found.")

    return db_user


@app.get("/u/tg/{tg_user_id}", response_model=schemas.User)
def user_get_tg(tg_user_id: int, db: DB = Depends(dbase.yield_with_session)):
    db_user = crud.user_get_by_tgid(db, tg_user_id)

    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found.")

    return db_user


@app.get("/u/{user_pk}/a/{address}", response_model=schemas.UserAddr)
def user_addr_get(user_pk: int, address: str, db: DB = Depends(dbase.yield_with_session)):
    db_user = crud.user_get_by_pkid(db, user_pk)

    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found.")

    return crud.user_addr_get(db=db, user=db_user, address=address)


@app.post("/u/{user_pk}/a/", response_model=schemas.UserAddr)
def user_addr_add(user_pk: int, addr_add: schemas.UserAddrAdd, db: DB = Depends(dbase.yield_with_session)):
    db_user = crud.user_get_by_pkid(db, user_pk)

    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found.")

    return crud.user_addr_add(db=db, user=db_user, addr_add=addr_add)


@app.post("/u/{user_pk}/a/{user_addr_pk}", response_model=schemas.DeleteResult)
def user_addr_del(user_pk: int, user_addr_pk: int, db: DB = Depends(dbase.yield_with_session)):
    db_user = crud.user_get_by_pkid(db, user_pk)

    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found.")

    return crud.user_addr_del(db=db, user=db_user, user_addr_pk=user_addr_pk)


@app.post("/u/{user_pk}/a/{user_addr_pk}/{addr_hist_pk}", response_model=schemas.DeleteResult)
def user_addr_hist_del(user_pk: int, user_addr_pk: int, addr_hist_pk: int, db: DB = Depends(dbase.yield_with_session)):
    db_user = crud.user_get_by_pkid(db, user_pk)

    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found.")

    user_addr: models.UserAddr = db.Session.query(
        models.UserAddr
    ).where(
        and_(
            models.UserAddr.user_pk == user_pk,
            models.UserAddr.pkid == user_addr_pk,
        )
    ).one_or_none()

    if user_addr is None:
        raise HTTPException(status_code=404, detail="UserAddr not found.")

    return crud.user_addr_hist_del(db=db, user_addr=user_addr, addr_hist_pk=addr_hist_pk)



# Use as template for Addrs.
# @app.get("/users/", response_model=List[schemas.User])
# def read_users(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
#     users = crud.get_users(db, skip=skip, limit=limit)
#     return users
