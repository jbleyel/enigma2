/*
Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License

Copyright (c) 2025 OpenATV, jbleyel

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
1. Non-Commercial Use: You may not use the Software or any derivative works
	 for commercial purposes without obtaining explicit permission from the
	 copyright holder.
2. Share Alike: If you distribute or publicly perform the Software or any
	 derivative works, you must do so under the same license terms, and you
	 must make the source code of any derivative works available to the
	 public.
3. Attribution: You must give appropriate credit to the original author(s)
	 of the Software by including a prominent notice in your derivative works.
THE SOFTWARE IS PROVIDED "AS IS," WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE, AND NONINFRINGEMENT. IN NO EVENT SHALL
THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES, OR
OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT, OR OTHERWISE,
ARISING FROM, OUT OF, OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
OTHER DEALINGS IN THE SOFTWARE.

For more details about the CC BY-NC-SA 4.0 License, please visit:
https://creativecommons.org/licenses/by-nc-sa/4.0/
*/

#include <cstring>
#include <iostream>
#include <net/if.h>
#include <string>
#include <sys/ioctl.h>
#include <unistd.h>

#include <algorithm>
#include <fcntl.h>
#include <regex>
#include <sstream>
#include <string.h>
#include <unistd.h>

#include <iomanip>


#include <lib/base/cfile.h>
#include <lib/base/ebase.h>
#include <lib/base/eerror.h>
#include <lib/base/init.h>
#include <lib/base/init_num.h>
#include <lib/base/modelinformation.h>
#include <lib/driver/edb.h>

#include <include/SQLiteWrapper.hpp>

/*

std::string getUniqueID(const std::string& device = "eth0") {
	eModelInformation& modelinformation = eModelInformation::getInstance();
	std::string model = modelinformation.getValue("model");
	int sock = socket(AF_INET, SOCK_DGRAM, 0);
	if (sock < 0) {
		perror("Socket creation failed");
		return "";
	}

	struct ifreq ifr;
	std::memset(&ifr, 0, sizeof(ifr));
	std::strncpy(ifr.ifr_name, device.c_str(), IFNAMSIZ - 1);

	if (ioctl(sock, SIOCGIFHWADDR, &ifr) < 0) {
		perror("IOCTL failed");
		close(sock);
		return "";
	}

	close(sock);

	std::ostringstream keyStream;
	for (int i = 0; i < 6; ++i) {
		keyStream << std::hex << std::setw(2) << std::setfill('0')
				  << (unsigned int)(unsigned char)ifr.ifr_hwaddr.sa_data[i];
	}
	std::string key = keyStream.str();

	std::string keyid;
	int j = key.length() - 1;
	for (size_t i = 0; i < key.length(); ++i) {
		if (i < model.length()) {
			keyid += key[j] + model[i] + key[i];
		} else {
			keyid += key[j] + key[i];
		}
		--j;
	}

	return keyid.substr(0, 12);
}

// Dummy DatabaseState class for compilation
class DatabaseState {
public:
	DatabaseState(const std::string& dbfile, const std::string& boxid) {}
	bool isRemoteLocked() {
		return false;
	}
	void lockDB() {}
	void unlockDB() {}
	std::vector<std::string> available_stbs;
	bool checkRemoteLock = false;
};

// Helper function to convert map to string for debugging
template <typename K, typename V> std::string toString(const std::map<K, V>& m) {
	std::stringstream ss;
	ss << "{";
	for (const auto& p : m) {
		ss << p.first << ": " << p.second << ", ";
	}
	ss << "}";
	return ss.str();
}

// Helper function to convert vector to string for debugging
template <typename T> std::string toString(const std::vector<T>& v) {
	std::stringstream ss;
	ss << "[";
	for (const auto& elem : v) {
		ss << elem << ", ";
	}
	ss << "]";
	return ss.str();
}

enum LogLevel { ERROR = 4, WARN = 3, INFO = 2, ALL = 1 };

CommonDataBase::CommonDataBase(const std::string& dbFile)
	: db(nullptr), cursor(nullptr), locked(false), dbthreadKill(false), dbthreadRunning(false),
	  dbthreadName("Update Database"), isInitiated(false), ignoreThreadCheck(false) {
	std::string dbPath = "/media/hdd/";
	if (!std::filesystem::exists(dbPath)) {
		dbPath = "/media/hdd/";
	}
	this->dbFile = dbPath + (dbFile.empty() ? "moviedb.db" : dbFile);
	debugPrint("Init database: " + this->dbFile, INFO);
}

CommonDataBase::~CommonDataBase() {
	closeDB();
}

bool CommonDataBase::connectDataBase(bool readonly) {
	std::lock_guard<std::mutex> lock(dbMutex);

	if (!isInitiated) {
		doInit();
	}

	if (!ignoreThreadCheck && dbthreadId != std::thread::id() && !readonly) {
		if (std::this_thread::get_id() != dbthreadId) {
			debugPrint("Connecting failed --> THREAD error! Another thread is using the database", ERROR);
			return false;
		}
	}

	if (locked && !readonly) {
		debugPrint("Connecting failed --> database locked!", ERROR);
		return false;
	}

	if (!db) {
		if (!std::filesystem::exists(std::filesystem::path(dbFile).parent_path())) {
			debugPrint("Connect table failed --> directory does not exist", ERROR);
			return false;
		}

		int flags = readonly ? SQLITE_OPEN_READONLY : (SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE);
		if (sqlite3_open_v2(dbFile.c_str(), &db, flags, nullptr) != SQLITE_OK) {
			debugPrint("Failed to open database: " + std::string(sqlite3_errmsg(db)), ERROR);
			return false;
		}

		executeSQL("PRAGMA case_sensitive_like=ON;", {}, true);
	}

	return (db != nullptr && !table.empty());
}

bool CommonDataBase::commitDB() {
	std::lock_guard<std::mutex> lock(dbMutex);

	if (!db) {
		debugPrint("Database not opened --> skip committing", ERROR);
		return false;
	}

	bool hasError = true;
	char* errMsg = nullptr;

	if (sqlite3_exec(db, "COMMIT", nullptr, nullptr, &errMsg) == SQLITE_OK) {
		hasError = false;
	} else {
		debugPrint("ERROR at committing database changes: " + std::string(errMsg ? errMsg : "Unknown error"), ERROR);
		sqlite3_free(errMsg);
	}

	if (hasError) {
		debugPrint("Error during committing changes", ERROR);
	}

	return !hasError;
}

void CommonDataBase::closeDB() {
	std::lock_guard<std::mutex> lock(dbMutex);

	if (!db) {
		debugPrint("Database not opened --> skip closing", ERROR);
		return;
	}

	if (cursor) {
		sqlite3_finalize(cursor);
		cursor = nullptr;
	}

	if (sqlite3_close(db) != SQLITE_OK) {
		debugPrint("Error closing database: " + std::string(sqlite3_errmsg(db)), ERROR);
	}
	db = nullptr;
}

void CommonDataBase::disconnectDataBase(bool readonly) {
	if (cursor) {
		debugPrint("Disconnect table " + table + " of database: " + dbFile, ALL);

		if (!ignoreThreadCheck && dbthreadId != std::thread::id() && std::this_thread::get_id() != dbthreadId) {
			debugPrint("Connecting failed --> THREAD error! Another thread is using the database", ERROR);
			return;
		}

		if (!readonly) {
			commitDB();
		}
		closeDB();
		cursor = nullptr;
	}
}

bool CommonDataBase::executeSQL(const std::string& sqlcmd, const std::vector<std::string>& args, bool readonly) {
	std::lock_guard<std::mutex> lock(dbMutex);

	if (!connectDataBase(readonly)) {
		return false;
	}

	debugPrint("SQL cmd: " + sqlcmd, ALL);
	if (!args.empty()) {
		debugPrint("SQL arguments: " + toString(args), ALL);
	}

	if (!readonly) {
		locked = true;
	}

	bool hasError = true;
	sqlite3_stmt* stmt = nullptr;
	std::vector<std::vector<std::string>> ret;

	try {
		if (sqlite3_prepare_v2(db, sqlcmd.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
			throw std::runtime_error(sqlite3_errmsg(db));
		}

		for (size_t i = 0; i < args.size(); ++i) {
			if (sqlite3_bind_text(stmt, i + 1, args[i].c_str(), -1, SQLITE_STATIC) != SQLITE_OK) {
				throw std::runtime_error(sqlite3_errmsg(db));
			}
		}

		if (readonly) {
			while (sqlite3_step(stmt) == SQLITE_ROW) {
				std::vector<std::string> row;
				for (int i = 0; i < sqlite3_column_count(stmt); ++i) {
					const char* colValue = reinterpret_cast<const char*>(sqlite3_column_text(stmt, i));
					row.push_back(colValue ? colValue : "");
				}
				ret.push_back(row);
			}
		} else {
			if (sqlite3_step(stmt) != SQLITE_DONE) {
				throw std::runtime_error(sqlite3_errmsg(db));
			}
		}

		hasError = false;
	} catch (const std::exception& errmsg) {
		std::string txt = "Database ERROR at SQL command: " + sqlcmd + "\n" + errmsg.what();
		debugPrint(txt, ERROR);
		disconnectDataBase();
	}

	if (!readonly) {
		locked = false;
	}

	sqlite3_finalize(stmt);
	return !hasError;
}

void CommonDataBase::doVacuum() {
	if (connectDataBase()) {
		executeSQL("VACUUM");
		disconnectDataBase();
	}
}

void CommonDataBase::createTable(const std::map<std::string, std::string>& fields) {
	if (!table.empty() && connectDataBase()) {
		std::stringstream field_str;
		field_str << "(";
		for (const auto& [name, type] : fields) {
			field_str << name << " " << type << ",";
		}
		std::string fieldDef = field_str.str();
		if (fieldDef.back() == ',') {
			fieldDef.pop_back();
		}
		fieldDef += ")";

		std::string sql = "CREATE TABLE IF NOT EXISTS " + table + " " + fieldDef;
		executeSQL(sql);
		commitDB();
	}
}

void CommonDataBase::checkTableColumns(const std::map<std::string, std::string>& fields, bool force_remove) {
	if (!table.empty() && connectDataBase()) {
		auto struc = getTableStructure();
		for (const auto& [column, type] : fields) {
			if (struc.find(column) == struc.end()) {
				std::string sqlcmd = "ALTER TABLE " + table + " ADD COLUMN " + column + " " + type + ";";
				executeSQL(sqlcmd);
			}
		}
		tableStructure.clear();
		commitDB();
	}
}

void CommonDataBase::createTableIndex(const std::string& idx_name, const std::vector<std::string>& fields,
									  bool unique) {
	if (!table.empty() && connectDataBase()) {
		std::string unique_txt = unique ? "UNIQUE" : "";
		std::string idxFields;
		for (const auto& field : fields) {
			idxFields += field + ", ";
		}
		if (!idxFields.empty()) {
			idxFields.resize(idxFields.length() - 2);
		}
		std::string sqlcmd =
			"CREATE " + unique_txt + " INDEX IF NOT EXISTS " + idx_name + " ON " + table + " (" + idxFields + ");";
		executeSQL(sqlcmd);
	}
}

void CommonDataBase::dropTable() {
	if (!table.empty() && connectDataBase()) {
		tableStructure.clear();
		executeSQL("DROP TABLE IF EXISTS " + table + ";");
	}
}

std::vector<std::string> CommonDataBase::getTables() {
	std::vector<std::string> tables;
	if (connectDataBase()) {
		sqlite3_stmt* stmt;
		const char* sql = "SELECT name FROM sqlite_master WHERE type='table';";

		if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) == SQLITE_OK) {
			while (sqlite3_step(stmt) == SQLITE_ROW) {
				const char* tableName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
				debugPrint("Found table: " + std::string(tableName), ALL);
				tables.push_back(tableName);
			}
		}
		sqlite3_finalize(stmt);
	}
	return tables;
}

std::map<std::string, std::string> CommonDataBase::getTableStructure() {
	if (tableStructure.empty()) {
		std::map<std::string, std::string> structure;
		if (!table.empty() && connectDataBase()) {
			std::string sql = "PRAGMA table_info('" + table + "');";
			sqlite3_stmt* stmt;

			if (sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr) == SQLITE_OK) {
				while (sqlite3_step(stmt) == SQLITE_ROW) {
					std::string columnName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
					std::string columnType = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
					structure[columnName] = columnType;
				}
				sqlite3_finalize(stmt);
				debugPrint("Data structure of table: " + table + "\n" + toString(structure), ALL);
			}
			tableStructure = structure;
		}
		return structure;
	}
	return tableStructure;
}

void CommonDataBase::addColumn(const std::string& column, const std::string& c_type) {
	if (connectDataBase()) {
		auto struc = getTableStructure();
		if (!table.empty() && struc.find(column) == struc.end()) {
			std::string sqlcmd = "ALTER TABLE " + table + " ADD COLUMN " + column + " " + c_type + ";";
			executeSQL(sqlcmd);
			tableStructure.clear();
		}
	}
}

std::vector<std::vector<std::string>> CommonDataBase::getTableContent() {
	std::vector<std::vector<std::string>> content;
	if (!table.empty() && connectDataBase()) {
		std::string sql = "SELECT * FROM " + table + ";";
		sqlite3_stmt* stmt;

		if (sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr) == SQLITE_OK) {
			int colCount = sqlite3_column_count(stmt);
			int rowCount = 1;

			while (sqlite3_step(stmt) == SQLITE_ROW) {
				std::vector<std::string> row;
				for (int i = 0; i < colCount; i++) {
					const char* value = reinterpret_cast<const char*>(sqlite3_column_text(stmt, i));
					row.push_back(value ? value : "");
				}
				content.push_back(row);
				debugPrint("Found row (" + std::to_string(rowCount++) + "):" + toString(row), ALL);
			}
		}
		sqlite3_finalize(stmt);
	}
	return content;
}

std::vector<std::vector<std::string>> CommonDataBase::searchDBContent(const std::map<std::string, std::string>& data,
																	  const std::string& fields,
																	  const std::string& query_type, bool exactmatch,
																	  const std::string& compareoperator) {
	std::vector<std::vector<std::string>> content;
	if (data.empty())
		return content;

	std::string wildcard = exactmatch ? "" : "%";
	std::string compare = (compareoperator.empty()) ? (exactmatch ? "=" : "LIKE") : compareoperator;
	std::string sql = "SELECT " + fields + " FROM " + table + " WHERE ";
	std::vector<std::string> args;

	for (const auto& [key, value] : data) {
		if (tableStructure.find(key) == tableStructure.end())
			continue;
		sql += key + " " + compare + " ? AND ";
		args.push_back(wildcard + value + wildcard);
	}

	sql = sql.substr(0, sql.length() - 5); // Remove trailing " AND "
	sqlite3_stmt* stmt;
	if (connectDataBase()) {
		if (sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr) == SQLITE_OK) {
			for (size_t i = 0; i < args.size(); ++i) {
				sqlite3_bind_text(stmt, i + 1, args[i].c_str(), -1, SQLITE_STATIC);
			}
			while (sqlite3_step(stmt) == SQLITE_ROW) {
				std::vector<std::string> row;
				for (int i = 0; i < sqlite3_column_count(stmt); ++i) {
					const char* value = reinterpret_cast<const char*>(sqlite3_column_text(stmt, i));
					row.push_back(value ? value : "");
				}
				content.push_back(row);
			}
		}
		sqlite3_finalize(stmt);
	}
	return content;
}

void CommonDataBase::insertRow(const std::map<std::string, std::string>& data, const std::string& uniqueFields) {
	if (connectDataBase()) {
		auto struc = getTableStructure();
		bool isValid = true;

		for (const auto& [field, value] : data) {
			if (struc.find(field) == struc.end()) {
				isValid = false;
				break;
			}
		}

		if (!table.empty() && isValid) {
			std::string sqlcmd = "INSERT INTO " + table + "(";
			std::string valuesPart = ") SELECT ";
			std::vector<std::string> args;

			for (const auto& [key, value] : data) {
				sqlcmd += key + ",";
				valuesPart += "\"" + value + "\",";
			}

			sqlcmd = sqlcmd.substr(0, sqlcmd.length() - 1);
			valuesPart = valuesPart.substr(0, valuesPart.length() - 1);

			if (!uniqueFields.empty()) {
				valuesPart += " WHERE NOT EXISTS(SELECT 1 FROM " + table + " WHERE " + uniqueFields + " =?)";
				if (data.find(uniqueFields) != data.end()) {
					args.push_back(data.at(uniqueFields));
				}
			}

			sqlcmd += valuesPart;
			executeSQL(sqlcmd, args);
		}
	}
}

void CommonDataBase::insertUniqueRow(const std::map<std::string, std::string>& data, bool replace) {
	if (!table.empty() && connectDataBase()) {
		auto struc = getTableStructure();
		for (const auto& [field, value] : data) {
			if (struc.find(field) == struc.end())
				return;
		}

		std::string method = replace ? "REPLACE" : "IGNORE";
		std::string sqlcmd = "INSERT OR " + method + " INTO " + table + "(";
		std::string values = ") VALUES (";
		std::vector<std::string> args;

		for (const auto& [key, value] : data) {
			sqlcmd += key + ",";
			values += "?,";
			args.push_back(value);
		}

		sqlcmd = sqlcmd.substr(0, sqlcmd.length() - 1);
		values = values.substr(0, values.length() - 1) + ");";
		sqlcmd += values;

		executeSQL(sqlcmd, args);
	}
}

void CommonDataBase::updateUniqueData(const std::map<std::string, std::string>& data,
									  const std::vector<std::string>& idxFields) {
	// First try to insert
	insertUniqueRow(data, false);

	// If insert failed (row exists), update
	if (cursor && changes() > 0) {
		std::string sql = "UPDATE " + table + " SET ";
		std::vector<std::string> args;

		for (const auto& [key, value] : data) {
			sql += key + "=?, ";
			args.push_back(value);
		}
		sql = sql.substr(0, sql.length() - 2); // Remove trailing comma

		sql += " WHERE ";
		for (const auto& field : idxFields) {
			if (data.find(field) != data.end()) {
				sql += field + "=? AND ";
				args.push_back(data.at(field));
			}
		}
		sql = sql.substr(0, sql.length() - 5); // Remove trailing AND

		executeSQL(sql, args);
	}
}

void CommonDataBase::updateData(const std::map<std::string, std::string>& data, const std::string& uniqueFields) {
	if (!table.empty() && connectDataBase()) {
		insertRow(data, uniqueFields);

		if (!cursor)
			return;
		if (changes() > 0)
			return;

		auto struc = getTableStructure();
		for (const auto& [field, value] : data) {
			if (struc.find(field) == struc.end())
				return;
		}

		std::vector<std::string> args;
		std::string sqlcmd = "UPDATE " + table + " SET ";

		for (const auto& [key, value] : data) {
			sqlcmd += key + "=?, ";
			args.push_back(value);
		}

		sqlcmd = sqlcmd.substr(0, sqlcmd.length() - 2);

		if (!uniqueFields.empty()) {
			sqlcmd += " WHERE " + uniqueFields + " =?";
			if (data.find(uniqueFields) != data.end()) {
				args.push_back(data.at(uniqueFields));
			}
		}

		executeSQL(sqlcmd, args);
	}
}

void CommonDataBase::deleteDataSet(const std::map<std::string, std::string>& fields, bool exactmatch) {
	if (connectDataBase()) {
		auto struc = getTableStructure();
		std::string wildcard = exactmatch ? "" : "%";
		std::string op = exactmatch ? "=" : " LIKE ";
		std::string whereStr = " WHERE ";
		std::vector<std::string> args;

		for (const auto& [column, value] : fields) {
			if (struc.find(column) == struc.end())
				return;
			whereStr += column + op + "? AND ";
			args.push_back(wildcard + value + wildcard);
		}

		whereStr = whereStr.substr(0, whereStr.length() - 5) + ";";
		std::string sqlcmd = "DELETE FROM " + table + whereStr;
		executeSQL(sqlcmd, args);
	}
}

bool CommonDataBase::checkThread() const {
	if (!ignoreThreadCheck && dbthreadId != std::thread::id() && std::this_thread::get_id() != dbthreadId) {
		debugPrint("Thread error: another thread is using the database", ERROR);
		return false;
	}
	return true;
}

bool CommonDataBase::isValidField(const std::string& field) const {
	return tableStructure.find(field) != tableStructure.end();
}

int CommonDataBase::changes() {
	return db ? sqlite3_changes(db) : 0;
}

void CommonDataBase::debugPrint(const std::string& message, int level) const {
	if (level >= 2) { // INFO level
		std::cout << "[Database] " << message << std::endl;
	}
}
*/
eMediaDB* eMediaDB::m_instance = nullptr;

eMediaDB::eMediaDB() {
	m_instance = this;
	eDebug("SQLite::VERSION %s", SQLite::SQLiteWrapper::getVersion().c_str());
}

eMediaDB::~eMediaDB() {
	m_instance = nullptr;
}

eMediaDB::init(std::string path) {

	try {
		SQLite::SQLiteWrapper db(path);
		db.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT, age INTEGER)");
		db.executePrepared("INSERT INTO users (name, age) VALUES (?, ?)", {"Alice", "30"});
		db.executePrepared("INSERT INTO users (name, age) VALUES (?, ?)", {"Bob", "25"});

		auto result = db.queryPrepared("SELECT id, name, age FROM users WHERE age > ?", {"26"});

		// Display the results
		for (const auto& row : result) {
			eDebug("[eMediaDB] DEBUG ID: %s, Name: %s, Age: %s\n", row[0].c_str(), row[1].c_str(), row[2].c_str());
		}

	} catch (const std::exception& e) {
		eDebug("[eMediaDB] Error Init: %s", e.what());
	}

    m_instance = this;
}


eAutoInitP0<eMediaDB> init_mediadb(eAutoInitNumbers::rc, "eMediaDB Driver");


/*

#include <iostream>
#include "SQLiteWrapper.hpp"

int main() {
	try {
		// Open (or create if not exist) SQLite database
		SQLite::SQLiteWrapper db("example.db");

		// Create a table
		db.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT, age INTEGER)");

		// Insert data with a prepared statement
		db.executePrepared("INSERT INTO users (name, age) VALUES (?, ?)", {"Alice", "30"});
		db.executePrepared("INSERT INTO users (name, age) VALUES (?, ?)", {"Bob", "25"});

		// Query data with a prepared statement
		auto result = db.queryPrepared("SELECT id, name, age FROM users WHERE age > ?", {"26"});

		// Display the results
		for (const auto& row : result) {
			std::cout << "ID: " << row[0] << ", Name: " << row[1] << ", Age: " << row[2] << std::endl;
		}

		// Output SQLite version
		std::cout << "SQLite Version: " << SQLite::SQLiteWrapper::getVersion() << std::endl;

		// Perform VACUUM on the database
		db.vacuum();
		std::cout << "VACUUM executed!" << std::endl;

	} catch (const std::exception& e) {
		std::cerr << "Error: " << e.what() << std::endl;
	}

	return 0;
}



*/