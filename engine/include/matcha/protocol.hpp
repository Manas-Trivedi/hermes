#pragma once
#include <string>
#include <string_view>
#include <matcha/order_book.hpp>

// Longest accepted command line, newline excluded (see PROTOCOL.md).
constexpr size_t MAX_LINE = 128;

// Runs one protocol command (without its trailing newline) against the book
// and returns the complete reply, every line newline-terminated.
std::string handle_command(OrderBook &book, std::string_view line);
