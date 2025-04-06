#ifndef SQLITE_WRAPPER_HPP
#define SQLITE_WRAPPER_HPP

#include <sqlite3.h>
#include <string>
#include <stdexcept>
#include <vector>
#include <iostream>
#include <memory>

namespace SQLite {

    class SQLiteWrapper {
    public:
        SQLiteWrapper(const std::string& db_name) {
            // Open SQLite database
            if (sqlite3_open(db_name.c_str(), &db) != SQLITE_OK) {
                throw std::runtime_error("Failed to open database: " + std::string(sqlite3_errmsg(db)));
            }
        }

        ~SQLiteWrapper() {
            if (db) {
                sqlite3_close(db);
            }
        }

        // Execute SQL without returning results
        void execute(const std::string& sql) {
            char* errMsg = nullptr;
            if (sqlite3_exec(db, sql.c_str(), nullptr, nullptr, &errMsg) != SQLITE_OK) {
                std::string err = errMsg ? errMsg : "Unknown error";
                sqlite3_free(errMsg);
                throw std::runtime_error("Error executing SQL command: " + err);
            }
        }

        // Execute SQL and fetch results
        std::vector<std::vector<std::string>> query(const std::string& sql) {
            sqlite3_stmt* stmt;
            if (sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
                throw std::runtime_error("Error preparing SQL statement: " + std::string(sqlite3_errmsg(db)));
            }

            std::vector<std::vector<std::string>> result;
            while (sqlite3_step(stmt) == SQLITE_ROW) {
                std::vector<std::string> row;
                int colCount = sqlite3_column_count(stmt);
                for (int col = 0; col < colCount; ++col) {
                    const char* value = reinterpret_cast<const char*>(sqlite3_column_text(stmt, col));
                    row.push_back(value ? value : "NULL");
                }
                result.push_back(row);
            }

            sqlite3_finalize(stmt);
            return result;
        }

        // Execute SQL and return results using prepared statements
        void executePrepared(const std::string& sql, const std::vector<std::string>& params) {
            sqlite3_stmt* stmt;
            if (sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
                throw std::runtime_error("Error preparing SQL statement: " + std::string(sqlite3_errmsg(db)));
            }

            // Bind parameters
            for (int i = 0; i < params.size(); ++i) {
                if (sqlite3_bind_text(stmt, i + 1, params[i].c_str(), -1, SQLITE_STATIC) != SQLITE_OK) {
                    sqlite3_finalize(stmt);
                    throw std::runtime_error("Error binding parameters: " + std::string(sqlite3_errmsg(db)));
                }
            }

            // Execute SQL
            if (sqlite3_step(stmt) != SQLITE_DONE) {
                sqlite3_finalize(stmt);
                throw std::runtime_error("Error executing SQL statement: " + std::string(sqlite3_errmsg(db)));
            }

            sqlite3_finalize(stmt);
        }

        // Execute SQL and fetch results using prepared statements
        std::vector<std::vector<std::string>> queryPrepared(const std::string& sql, const std::vector<std::string>& params) {
            sqlite3_stmt* stmt;
            if (sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
                throw std::runtime_error("Error preparing SQL statement: " + std::string(sqlite3_errmsg(db)));
            }

            // Bind parameters
            for (int i = 0; i < params.size(); ++i) {
                if (sqlite3_bind_text(stmt, i + 1, params[i].c_str(), -1, SQLITE_STATIC) != SQLITE_OK) {
                    sqlite3_finalize(stmt);
                    throw std::runtime_error("Error binding parameters: " + std::string(sqlite3_errmsg(db)));
                }
            }

            std::vector<std::vector<std::string>> result;
            while (sqlite3_step(stmt) == SQLITE_ROW) {
                std::vector<std::string> row;
                int colCount = sqlite3_column_count(stmt);
                for (int col = 0; col < colCount; ++col) {
                    const char* value = reinterpret_cast<const char*>(sqlite3_column_text(stmt, col));
                    row.push_back(value ? value : "NULL");
                }
                result.push_back(row);
            }

            sqlite3_finalize(stmt);
            return result;
        }

        // Perform VACUUM to optimize the database
        void vacuum() {
            execute("VACUUM");
        }

    public:
        // Static function to get the SQLite library version
        static std::string getVersion() {
            return sqlite3_libversion();
        }

    private:
        sqlite3* db = nullptr;
    };

} // namespace SQLite

#endif // SQLITE_WRAPPER_HPP
