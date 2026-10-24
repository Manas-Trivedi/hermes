#include <gtest/gtest.h>
#include <string>
#include <vector>
#include <matcha/protocol.hpp>

TEST(ProtocolTest, CrossingOrderRepliesWithTrade) {
    OrderBook book(10);
    EXPECT_EQ(handle_command(book, "SELL 1 100 2"), "OK 0\n");
    EXPECT_EQ(handle_command(book, "BUY 8 105 1"), "OK 1\nTRADE 8 1 100 1\n");
    EXPECT_EQ(handle_command(book, "MSELL 9 1"), "OK 0\n");
    EXPECT_EQ(handle_command(book, "MBUY 10 1"), "OK 1\nTRADE 10 1 100 1\n");
}

TEST(ProtocolTest, StatusesMapToErrorCodes) {
    OrderBook book(1);
    EXPECT_EQ(handle_command(book, "BUY 1 100 1"), "OK 0\n");
    EXPECT_EQ(handle_command(book, "BUY 1 100 1"), "ERR DUPLICATE_ID\n");
    EXPECT_EQ(handle_command(book, "BUY 2 100 1"), "ERR ARENA_FULL\n");
    EXPECT_EQ(handle_command(book, "CANCEL 1"), "OK 0\n");
    EXPECT_EQ(handle_command(book, "CANCEL 1"), "ERR UNKNOWN_ID\n");
}

TEST(ProtocolTest, MalformedLinesAreRejectedAndLeaveBookUntouched) {
    OrderBook book(10);
    ASSERT_EQ(handle_command(book, "SELL 1 100 1"), "OK 0\n");

    const std::vector<std::string> bad = {
        "", " ", "BUY", "BUY 2 100", "BUY 2 100 1 1", "MBUY 2 100 1", "CANCEL", "CANCEL 1 2",
        "BOOK 1", "buy 2 100 1", "FOO 2 100 1",
        "BUY  2 100 1", " BUY 2 100 1", "BUY 2 100 1 ",
        "BUY -1 100 1", "BUY +2 100 1", "BUY 2 1x 1", "BUY 2 1.5 1",
        "BUY 2 100 18446744073709551616",
        "BUY 2 0 1", "BUY 2 100 0", "MBUY 2 0", "SELL 2 100 1\r",
        std::string("BUY 2 100 1") + std::string(MAX_LINE, ' '),
    };
    for(const std::string &line : bad) {
        EXPECT_EQ(handle_command(book, line), "ERR BAD_COMMAND\n") << "line: [" << line << "]";
    }
    // none of them reached the book
    EXPECT_EQ(handle_command(book, "BOOK"), "OK 1\nASK 100 1 1\n");
}

TEST(ProtocolTest, EdgeValuesAreAccepted) {
    OrderBook book(10);
    EXPECT_EQ(handle_command(book, "BUY 0 18446744073709551615 18446744073709551615"), "OK 0\n");
}

TEST(ProtocolTest, BookListsBidsThenAsksBestFirstWithTimePriority) {
    OrderBook book(10);
    handle_command(book, "BUY 1 90 1");
    handle_command(book, "BUY 2 95 2");
    handle_command(book, "BUY 3 95 3");
    handle_command(book, "SELL 4 110 1");
    handle_command(book, "SELL 5 105 1");
    EXPECT_EQ(handle_command(book, "BOOK"),
              "OK 5\n"
              "BID 95 2 2\nBID 95 3 3\nBID 90 1 1\n"
              "ASK 105 1 5\nASK 110 1 4\n");
}
