#!/usr/bin/env python3
"""Python re-implementation of src/program.cbl (BOOKFORUM).

Mirrors the behaviour of the program when built with GnuCOBOL 3, including
the runtime's handling of odd data (non-digit bytes in numeric fields,
truncated files, run-time aborts on failed I/O).

Like the COBOL program it is meant to be run from the cobol/ directory;
paths are resolved relative to this file so it works from anywhere.
"""
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ACCOUNTS = os.path.join(BASE, "data", "ACCOUNTS.DAT")
BOOKS = os.path.join(BASE, "data", "BOOKS.DAT")
TRANSACTIONS = os.path.join(BASE, "data", "TRANSACTIONS.DAT")
INPUT = os.path.join(BASE, "src", "INPUT.DAT")

ACC_LEN = 34   # ACCOUNT-ID X(4) + ACCOUNT-NAME X(20) + ACCOUNT-BALANCE 9(10)
BOOK_LEN = 28  # BOOK-ID X(4) + BOOK-TITLE X(20) + BOOK-OWNER X(4)
IN_LEN = 22    # BUYER X(4) + SELLER X(4) + BOOK X(4) + AMOUNT 9(10)
MOD = 10 ** 10


class Abort(Exception):
    """libcob run-time error: the COBOL program stops immediately."""


class SeqFile:
    """Fixed-length ORGANIZATION SEQUENTIAL file as handled by libcob.

    The record area and the current record size live as long as the
    program: a short read at end of file shrinks the record size (which is
    never reset) and leaves the rest of the record area untouched.
    """

    def __init__(self, path, length):
        self.path = path
        self.length = length
        self.size = length
        self.record = bytearray(length)
        self.fh = None
        self.read_done = False

    def open(self, mode):
        try:
            self.fh = open(self.path, mode)
        except OSError:
            raise Abort("cannot open " + self.path)
        self.read_done = False

    def close(self):
        self.fh.close()
        self.fh = None

    def read(self):
        """Return False at end of file, True when a record was read."""
        self.read_done = False
        data = self.fh.read(self.size)
        if not data:
            return False
        self.record[:len(data)] = data
        self.size = len(data)
        self.read_done = True
        return True

    def rewrite(self):
        read_done, self.read_done = self.read_done, False
        if not read_done:
            raise Abort("READ must be executed first (status = 43)")
        if self.size != self.length:
            raise Abort("record overflow (status = 44)")
        self.fh.seek(-self.size, os.SEEK_CUR)
        self.fh.write(self.record)
        self.fh.flush()


def numeric_value(raw):
    """Value libcob computes for an unsigned DISPLAY field (digits only)."""
    if raw[0] == 0xFF:
        return 10 ** len(raw)
    if raw[0] == 0x00:
        return -(10 ** len(raw))
    value = 0
    for b in raw:
        value = value * 10 + (b & 0x0F)
    return value


def store_balance(value):
    """Store into unsigned PIC 9(10): sign dropped, high digits truncated."""
    return b"%010d" % (abs(value) % MOD)


def move_numeric(raw):
    """MOVE between unsigned DISPLAY items: bytes copied as-is, except that
    spaces and low-values become zeros."""
    return bytes(0x30 if b in (0x00, 0x20) else b for b in raw)


def run():
    try:
        with open(INPUT, "rb") as f:
            raw = f.read(IN_LEN)
    except OSError:
        raise Abort("cannot open " + INPUT)
    if not raw:
        print("Error: Input file is empty")
        return
    rec = raw + b"\x00" * (IN_LEN - len(raw))
    buyer, seller, book = rec[0:4], rec[4:8], rec[8:12]
    ws_amount = move_numeric(rec[12:22])     # digits of WS-AMOUNT 9(10)V99
    amount = numeric_value(ws_amount + b"00") // 100

    accounts = SeqFile(ACCOUNTS, ACC_LEN)
    books = SeqFile(BOOKS, BOOK_LEN)

    # VALIDATE-USERS-AND-BOOK
    buyer_found = seller_found = book_found = valid_owner = False
    accounts.open("rb")
    while accounts.read():
        if accounts.record[0:4] == buyer:
            buyer_found = True
        if accounts.record[0:4] == seller:
            seller_found = True
    accounts.close()

    books.open("rb")
    while books.read():
        if books.record[0:4] == book:
            book_found = True
            if books.record[24:28] == seller:
                valid_owner = True
    books.close()
    print(" ")

    if not (buyer_found and seller_found and book_found and valid_owner):
        print("Transaction failed due to validation errors")
        return

    # PROCESS-TRANSACTION
    accounts.open("r+b")
    try:
        while accounts.read():
            r = accounts.record
            if r[0:4] == buyer:
                r[24:34] = store_balance(numeric_value(r[24:34]) - amount)
                accounts.rewrite()
            if r[0:4] == seller:
                r[24:34] = store_balance(numeric_value(r[24:34]) + amount)
                accounts.rewrite()
    finally:
        accounts.close()

    books.open("r+b")
    try:
        while books.read():
            if books.record[0:4] == book:
                books.record[24:28] = buyer
                books.rewrite()
    finally:
        books.close()

    # OPEN EXTEND fails (and the program aborts) if the file does not exist.
    if not os.path.isfile(TRANSACTIONS):
        raise Abort("file does not exist (status = 35)")
    with open(TRANSACTIONS, "ab") as f:
        f.write(book + move_numeric(ws_amount) + seller + buyer)

    print("Transaction completed successfully")


def main():
    try:
        run()
    except Abort as exc:
        sys.stderr.write("error: %s\n" % exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
