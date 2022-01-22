from __future__ import annotations

import asyncio
import time
from asyncio import CancelledError
from typing import Optional, List

from attrdict import AttrDict
from hydra import log
from sqlalchemy import Column, String, Integer, desc, UniqueConstraint, and_, or_
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import relationship

from .base import *
from .db import DB

__all__ = "Block",


class LocalState:
    # Testnet blocks:
    # 160387 (160388 is HYDRA SC TX + minting two tokens to sender)
    # 160544 (160545 is HYDRA TX)
    height = 0
    hash = ""


class Block(Base):
    __tablename__ = "block"
    __table_args__ = (
        UniqueConstraint("height", "hash"),
    )

    pkid = DbPkidColumn(seq="block_seq")
    height = Column(Integer, nullable=False, unique=False, primary_key=False, index=True)
    hash = Column(String(64), nullable=False, unique=True, primary_key=False, index=True)

    addr_hist = relationship(
        "AddrHist",
        back_populates="block",
        cascade="all, delete-orphan",
        single_parent=True,
    )

    info = DbInfoColumn()
    tx = DbDataColumn()

    def _removed_hist(self, db: DB):
        if not len(self.addr_hist):
            log.info(f"Deleting block #{self.height} with no history.")
            db.Session.delete(self)

    def on_new_block(self, db: DB) -> bool:
        info, txes = Block.__get_block_info(db, self.height, self.hash)

        addresses_hy = set()
        addresses_hx = set()

        for txid in info.transactions:
            tx = txes[txid]
            for vio in (tx.inputs + tx.outputs):
                if "addressHex" in vio:
                    addresses_hx.add(vio.addressHex)
                elif "address" in vio:
                    addresses_hy.add(vio.address)

        if not len(addresses_hy) and not len(addresses_hx):
            return False

        from .addr import Addr

        addrs: List[Addr] = db.Session.query(
            Addr,
        ).where(
            and_(
                # Addr.addr_tp == Addr.Type.H,
                or_(
                    Addr.addr_hy.in_(addresses_hy),
                    Addr.addr_hx.in_(addresses_hx),
                )
            )
        ).all()

        if not len(addrs):
            return False

        added_history = False

        self.info = info
        self.tx = txes

        for addr in addrs:
            added_history |= addr.update_info(db, block=self)

        return added_history

    @staticmethod
    def get(db: DB, height: int, create: Optional[bool] = True) -> Optional[Block]:
        try:
            block = db.Session.query(
                Block,
            ).where(
                Block.height == height,
            )

            if not create:
                return block.one_or_none()

            return block.one()
        except NoResultFound:
            return Block.make(db, height)

    @staticmethod
    def make(db: DB, height: int) -> Optional[Block]:
        bhash = db.rpc.getblockhash(height)

        # noinspection PyArgumentList
        new_block: Block = Block(
            height=height,
            hash=bhash,
        )

        db.Session.add(new_block)

        if new_block.on_new_block(db):
            db.Session.commit()
            db.Session.refresh(new_block)
            log.info(f"Added block with {len(new_block.addr_hist)} history entries at height {new_block.height}")
            return new_block

        log.debug(f"Discarding block without history entries at height {new_block.height}")
        db.Session.rollback()

    @staticmethod
    async def update_task_async(db: DB) -> None:
        # await asyncio.sleep(30)

        try:
            while 1:
                await Block.update_async(db)
                await asyncio.sleep(15)
        except KeyboardInterrupt:
            pass
        except CancelledError:
            pass

    @staticmethod
    async def update_async(db: DB) -> None:
        # noinspection PyBroadException
        try:
            if LocalState.height == 0:
                await db.in_session_async(Block.__update_init, db)

            return await db.in_session_async(Block.update, db)
        except KeyboardInterrupt:
            raise
        except CancelledError:
            raise
        except BaseException as exc:
            log.critical(f"Block.update exception: {str(exc)}", exc_info=exc)

    @staticmethod
    def update_task(db: DB) -> None:
        try:
            if LocalState.height == 0:
                Block.__update_init(db)

            while 1:
                Block.update(db)
                time.sleep(15)

        except KeyboardInterrupt:
            pass

    @staticmethod
    def __update_init(db: DB) -> None:
        block: Block = db.Session.query(
            Block
        ).order_by(
            desc(Block.height)
        ).limit(1).one_or_none()

        if block is not None:
            LocalState.height = block.height
            LocalState.hash = block.hash
        else:
            LocalState.height = db.rpc.getblockcount() - 1

    @staticmethod
    def update(db: DB) -> None:

        chain_height = db.rpc.getblockcount()
        chain_hash = db.rpc.getblockhash(chain_height)

        log.debug(f"Poll: chain={chain_height} local={LocalState.height}")

        if chain_height == LocalState.height:
            if chain_hash != LocalState.hash:
                log.warning(f"Fork detected at height {chain_height}: {chain_hash} != {LocalState.hash}")
            else:
                return

        for height in range(LocalState.height + 1, chain_height + 1):
            Block.make(db, height)

        LocalState.height = chain_height
        LocalState.hash = chain_hash

    @staticmethod
    def __get_block_info(db: DB, block_height: int, block_hash: str):
        info = db.rpcx.get_block(block_hash)

        if info.height != block_height or info.hash != block_hash:
            raise ValueError(f"Block info mismatch at height {block_height}/{info.height}")

        del info.hash
        del info.height

        tx = {}

        for n, transaction in enumerate(info.transactions):
            tx[transaction] = db.rpcx.get_tx(transaction)
            tx[transaction].n = n

        return info, tx

