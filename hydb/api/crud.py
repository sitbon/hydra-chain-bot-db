from typing import Optional

from hydb.db import DB
from hydb import db as models
from . import schemas


def server_info(db: DB) -> schemas.ServerInfo:
    return schemas.ServerInfo(mainnet=db.rpc.mainnet)


def user_get_by_tgid(db: DB, tg_user_id: int) -> Optional[models.User]:
    return db.Session.query(
        models.User
    ).where(
        models.User.tg_user_id == tg_user_id
    ).one_or_none()


def user_get_by_pkid(db: DB, user_pk: int) -> Optional[models.User]:
    return db.Session.query(
        models.User
    ).where(
        models.User.pkid == user_pk
    ).one_or_none()


def user_add(db: DB, user_create: schemas.UserCreate) -> models.User:
    return models.User.get(db, user_create.tg_user_id, create=True)


def user_del(db: DB, user_pk: int):
    u: models.User = db.Session.query(
        models.User
    ).where(
        models.User.pkid == user_pk
    ).one()

    u.delete(db)


def user_addr_get(db: DB, user: models.User, address: str) -> Optional[models.UserAddr]:
    return user.addr_get(
        db=db,
        address=address,
        create=False
    )


def user_addr_add(db: DB, user: models.User, addr_add: schemas.UserAddrAdd) -> models.UserAddr:
    return user.addr_get(
        db=db,
        address=addr_add.address,
        create=True
    )


def user_addr_del(db: DB, user: models.User, user_addr_pk: int) -> schemas.DeleteResult:
    # noinspection PyArgumentList
    return schemas.DeleteResult(
        deleted=user.addr_del(
            db=db,
            user_addr_pk=user_addr_pk
        )
    )


def user_addr_hist_del(db: DB, user_addr: models.UserAddr, addr_hist_pk: int) -> schemas.DeleteResult:
    # noinspection PyArgumentList
    return schemas.DeleteResult(
        deleted=user_addr.addr_hist_del(
            db=db,
            addr_hist_pk=addr_hist_pk
        )
    )
