import sqlite3

from lake.intake.provenance import require_identifier


class UnknownStation(LookupError):
    pass


def prepare_station_register(db: sqlite3.Connection) -> None:
    db.execute('CREATE TABLE IF NOT EXISTS stations (station TEXT PRIMARY KEY)')
    db.execute('''
        CREATE TABLE IF NOT EXISTS station_seed (
            singleton INTEGER PRIMARY KEY CHECK(singleton = 1)
        )
    ''')


def seed_stations(db: sqlite3.Connection, stations) -> None:
    if db.execute('SELECT 1 FROM station_seed WHERE singleton = 1').fetchone() is not None:
        return
    if isinstance(stations, (str, bytes)):
        raise ValueError('an initial station list must be an iterable of station identifiers')
    names = tuple(require_identifier(name, 'station') for name in stations)
    for name in names:
        register_station(db, name)
    db.execute('INSERT INTO station_seed VALUES (1)')


def register_station(db: sqlite3.Connection, station: str) -> None:
    name = require_identifier(station, 'station')
    db.execute('INSERT INTO stations VALUES (?) ON CONFLICT(station) DO NOTHING', (name,))


def require_station(db: sqlite3.Connection, station: str) -> None:
    station = require_identifier(station, 'station')
    if db.execute('SELECT 1 FROM stations WHERE station = ?', (station,)).fetchone() is None:
        raise UnknownStation(station)
