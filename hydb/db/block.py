from __future__ import annotations

import asyncio
import time
from asyncio import CancelledError
from typing import Optional, List

from hydra import log
from hydra.rpc import BaseRPC
from sqlalchemy import Column, String, Integer, desc, UniqueConstraint, and_, or_, func, select, asc
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import relationship

from .base import *
from .db import DB
from ..api import schemas

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
    conf = Column(Integer, nullable=False, index=True)
    info = DbInfoColumn()
    tx = DbDataColumn()

    addr_hist = relationship(
        "AddrHist",
        order_by="AddrHist.pkid",
        back_populates="block",
        cascade="all, delete-orphan",
        single_parent=True,
    )

    CONF_MATURE = 501

    def _removed_hist(self, db: DB):
        if not len(self.addr_hist):
            log.info(f"Deleting block #{self.height} with no history.")
            db.Session.delete(self)

    def on_new_block(self, db: DB) -> bool:
        info, txes = Block.__get_block_info(db, self.height, self.hash)

        addresses_hy = set()
        addresses_hx = set()

        for tx in txes:
            for address in schemas.Block.tx_yield_addrs(tx):
                if len(address) == 34:
                    addresses_hy.add(address)
                elif len(address) == 40:
                    addresses_hx.add(address)
                else:
                    log.warning(f"Unknown address length {len(address)}: '{address}'")

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

        self.conf = info["confirmations"]
        del info["confirmations"]
        self.info = info
        self.tx = txes

        for addr in addrs:
            added_history |= addr.on_block_create(db=db, block=self)

        return added_history

    def filter_tx(self, address: str):
        return filter(lambda tx: address in list(schemas.Block.tx_yield_addrs(tx)), self.tx)

    def update_confirmations(self, db: DB):
        confirmations = self.conf

        if confirmations < Block.CONF_MATURE:

            conf = db.rpc.getblockheader(blockhash=self.hash).confirmations

            if conf >= Block.CONF_MATURE:
                self.conf = conf

                if len(self.addr_hist):
                    for addr_hist in self.addr_hist:
                        addr_hist.on_block_mature()

                    db.Session.add(self)
                    db.Session.commit()

                    try:
                        db.api.sse_block_notify_mature(block_pk=self.pkid)
                    except BaseRPC.Exception as exc:
                        log.critical(f"Unable to send block mature notify: response={exc.response} error={exc.error}", exc_info=exc)
                    else:
                        log.info(f"Sent notification for matured block #{self.pkid}")
                else:
                    # This condition is currently not possible due to cascading deletes,
                    #  only because AddrHist.on_block_mature() never deletes (only happens post notify).
                    #
                    log.warning(f"Deleting matured block at height {self.height} with no history.")
                    db.Session.delete(self)
                    db.Session.commit()

    @staticmethod
    def update_confirmations_all(db: DB):
        """Update confirmations on stored blocks.
        """
        blocks: List[Block] = db.Session.query(
            Block
        ).order_by(
            asc(Block.height)
        ).filter(
            Block.conf < Block.CONF_MATURE
        ).all()

        for block in blocks:
            block.update_confirmations(db)

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

        if new_block.on_new_block(db):
            db.Session.add(new_block)
            db.Session.commit()
            db.Session.refresh(new_block)
            log.info(f"Added block with {len(new_block.addr_hist)} history entries at height {new_block.height}")

            try:
                db.api.sse_block_notify_create(block_pk=new_block.pkid)
            except BaseRPC.Exception as exc:
                log.critical(f"Unable to send block notify: response={exc.response} error={exc.error}", exc_info=exc)
            else:
                log.info(f"Sent notification for new block #{new_block.pkid}")

            return new_block

        log.debug(f"Discarding block without history entries at height {new_block.height}")
        db.Session.rollback()

    @staticmethod
    def update_task(db: DB) -> None:
        try:
            Block.__update_init(db)

            while 1:
                Block.update_confirmations_all(db)
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
            if LocalState.height == 0:
                LocalState.height = db.rpc.getblockcount() - 1

    @staticmethod
    def update(db: DB) -> None:

        chain_height = db.rpc.getblockcount()
        chain_hash = db.rpc.getblockhash(chain_height)

        log.debug(f"Poll: chain={chain_height} local={LocalState.height}")

        if chain_height == LocalState.height:
            if LocalState.hash and chain_hash != LocalState.hash:
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

        tx = []

        for txid in info.transactions:
            tx.append(db.rpcx.get_tx(txid))

        return info, tx

