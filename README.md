# Delay Scanner

## Welcome
Congrats, you found the **Delay Scanner**! We uploaded this tool for a submission, so right now it's just the plain code without, no `setup.py`, only some notes and hints. Feel free to take a look around, or try one of my other repositories.  

We'll improve all parts in the next days and weeks to make it easier to actually use the Delay Scanner.

**Have Fun!**

## Components
### Consensus Parser
Downloads the day's first relay-descriptor consensus file from collector and parses the contents to the fingerprints table of the database. We save the fingerprint, guard/relay/exit flag, continent code, country code, and reported bandwidth of each router in the consensus file.

The fingerprints table is used by the Circuit Builder and should be updated on a regular base. Nevertheless, an update must be invoked manually and should be followed by a Circuit Builder Update.

Example call:
```
python get_consensus.py --consensus-path ../consensus_files/consensus --db-name scanner_db --db-user scanner_db_user --db-passwd 8oh3ifn398f3
```

### Circuit Builder
Uses the entries of the fingerprints table and forms circuits from it, results are written to table ```circuits```. Building circuits follows a defined strategy that avoids re-use of guards but keeps exit nodes fixed. In particular this means:
- We use all possible variations of middle relays and guards for one exit node. Nevertheless,
- We do *not* use all combinations of middle relays and guard nodes. This means we advance the list of middle relays and guards at the same time.

Running the circuit builder should alway follow a fresh update of fingerprints, otherwise the circuits are not up to date and could include relays that are not available anymore.

Example call:
```
python get_circuits.py --db-name scanner_db --db-user scanner_db_user --db-passwd 8oh3ifn398f3
```

### Connect and Time


## Details
### General
```SQL
CREATE DATABASE `scanner_db`;
ALTER SCHEMA `scanner_db` DEFAULT CHARACTER SET utf8;
CREATE USER 'delayscanner_user'@'%' IDENTIFIED BY '8oh3ifn398f3';
GRANT SELECT, INSERT, UPDATE ON `scanner_db`.* TO 'scanner_db_user'@'%';

FLUSH PRIVILEGES;
```

### Consensus Parser
- Script: ```get_consensus.py```
- Database table: fingerprints

#### Options
```
  --consensus-path TEXT  path to consensus file
  --db-name TEXT         name of SQL DB
  --db-user TEXT         username for SQL DB
  --db-passwd TEXT       password for SQL DB
  --help                 Show this message and exit.
  ```

#### Imports and Dependencies
  - txtorcon
  - click
  - urllib
  - json
  - datetime
  - twisted
  - stem

#### Database
```SQL
CREATE TABLE fingerprints (
    fid INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    fp VARCHAR(255) NOT NULL UNIQUE,
    continent_code CHAR(2) NOT NULL,
    country_code CHAR(2) NOT NULL,
    bandwidth DOUBLE NOT NULL,
    above_avg_bw BOOLEAN NOT NULL,
    flag VARCHAR(5)
) ENGINE=InnoDB;
```

### Circuit Builder
- ```get_circuits.py```
- Database table: circuits

#### Options
```
--db-name TEXT    name of SQL DB
--db-user TEXT    username for SQL DB
--db-passwd TEXT  password for SQL DB
--help            Show this message and exit.
```

#### Imports and Dependencies
#### Database
```SQL
CREATE TABLE circuits (
    cid INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    entry_relay INT NOT NULL,
    middle_relay INT NOT NULL,
    exit_relay INT NOT NULL
) ENGINE=InnoDB;
```

### Connect and Time
- ```connect_tor.py```

#### Options
```
--tor-control INTEGER  tor control port from torrc config
--socks INTEGER        socks procy from torrc config
--db-name TEXT         name of SQL DB
--db-user TEXT         username for SQL DB
--db-passwd TEXT       password for SQL DB
--strategy TEXT        choose continent_code or country_code
--geo-code TEXT        choose continent or country according to srategy
--repetitions INTEGER  Number of repetitions per parameter combination
--period TEXT          enter [day] (6am - 6pm) or [night] (6pm - 6am)
--help                 Show this message and exit.
```

#### Database
```SQL
CREATE TABLE circuit_statistics (
	cid INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    build_offset VARCHAR(255) NOT NULL,
    strategy VARCHAR(255) NOT NULL,
    geo_code CHAR(2) NOT NULL,
    period CHAR(2) NOT NULL
) ENGINE=InnoDB;
```

```SQL
CREATE TABLE request_statistics (
	cid INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    request_offset VARCHAR(255) NOT NULL,
    strategy VARCHAR(255) NOT NULL,
    geo_code CHAR(2) NOT NULL,
    period CHAR(2) NOT NULL
) ENGINE=InnoDB;
```

```SQL
CREATE TABLE circuit_failures (
	cid INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    strategy VARCHAR(255) NOT NULL,
    geo_code CHAR(2) NOT NULL,
    period CHAR(2) NOT NULL,
    rate DOUBLE NOT NULL,
    repetitions DOUBLE NOT NULL
) ENGINE=InnoDB;
```
