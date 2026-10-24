#include <gtest/gtest.h>
#include <matcha/order_book.hpp>

TEST(OrderBookTest, MarketOrderNeverRests) {
    OrderBook book(10);

    Order order;
    order.id = 1;
    order.side = Side::BUY;
    order.order_type = OrderType::MARKET;
    order.qty = 5;

    book.insert_order(order);
    EXPECT_FALSE(book.contains_order(1));
}

static Order make_order(uint64_t id, Side side, OrderType type, uint64_t price, uint64_t qty) {
    Order o;
    o.id = id;
    o.side = side;
    o.order_type = type;
    o.price = price;
    o.qty = qty;
    return o;
}

static Order limit(uint64_t id, Side side, uint64_t price, uint64_t qty) {
    return make_order(id, side, OrderType::LIMIT, price, qty);
}

static Order market(uint64_t id, Side side, uint64_t qty) {
    return make_order(id, side, OrderType::MARKET, 0, qty);
}

static Order cancel(uint64_t id) {
    return make_order(id, Side::BUY, OrderType::CANCEL, 0, 0);
}

TEST(CancelTest, CancelledOrderNoLongerMatches) {
    OrderBook book(10);
    Order sell = limit(1, Side::SELL, 100, 5);
    book.insert_order(sell);
    Order c = cancel(1);
    book.insert_order(c);
    EXPECT_FALSE(book.contains_order(1));

    Order buy = limit(2, Side::BUY, 100, 5);
    book.insert_order(buy);
    EXPECT_TRUE(book.contains_order(2));
    EXPECT_EQ(book.get_order(2)->qty, 5u);
}

TEST(CancelTest, UnknownIdIsIgnored) {
    OrderBook book(10);
    Order o = limit(1, Side::BUY, 100, 5);
    book.insert_order(o);

    Order c = cancel(99);
    book.insert_order(c);
    EXPECT_TRUE(book.contains_order(1));
}

TEST(CancelTest, CancelMiddleOfLevelKeepsOthers) {
    OrderBook book(10);
    Order a = limit(1, Side::SELL, 100, 1);
    Order b = limit(2, Side::SELL, 100, 1);
    Order c = limit(3, Side::SELL, 100, 1);
    book.insert_order(a);
    book.insert_order(b);
    book.insert_order(c);

    Order x = cancel(2);
    book.insert_order(x);
    EXPECT_TRUE(book.contains_order(1));
    EXPECT_FALSE(book.contains_order(2));
    EXPECT_TRUE(book.contains_order(3));

    // the remaining two still fill in arrival order
    Order buy = limit(4, Side::BUY, 100, 1);
    book.insert_order(buy);
    EXPECT_FALSE(book.contains_order(1));
    EXPECT_TRUE(book.contains_order(3));
}

TEST(CancelTest, ArenaSlotIsReusedAfterCancel) {
    OrderBook book(1);
    Order a = limit(1, Side::BUY, 100, 5);
    book.insert_order(a);
    Order x = cancel(1);
    book.insert_order(x);

    Order b = limit(2, Side::BUY, 100, 5);
    book.insert_order(b);
    EXPECT_TRUE(book.contains_order(2));
}

TEST(PriorityTest, FifoWithinPriceLevel) {
    OrderBook book(10);
    Order first = limit(1, Side::SELL, 100, 5);
    Order second = limit(2, Side::SELL, 100, 5);
    book.insert_order(first);
    book.insert_order(second);

    Order buy = limit(3, Side::BUY, 100, 5);
    book.insert_order(buy);
    EXPECT_FALSE(book.contains_order(1));  // earlier order filled first
    EXPECT_TRUE(book.contains_order(2));
    EXPECT_EQ(book.get_order(2)->qty, 5u);
}

TEST(PriorityTest, FifoPartialFillKeepsQueuePosition) {
    OrderBook book(10);
    Order first = limit(1, Side::SELL, 100, 10);
    Order second = limit(2, Side::SELL, 100, 10);
    book.insert_order(first);
    book.insert_order(second);

    Order buy1 = limit(3, Side::BUY, 100, 4);
    book.insert_order(buy1);
    Order buy2 = limit(4, Side::BUY, 100, 4);
    book.insert_order(buy2);

    // order 1 absorbed both partial fills and is still ahead of order 2
    EXPECT_EQ(book.get_order(1)->qty, 2u);
    EXPECT_EQ(book.get_order(2)->qty, 10u);
}

TEST(PriorityTest, BuyHitsLowestAskFirst) {
    OrderBook book(10);
    Order high = limit(1, Side::SELL, 102, 5);
    Order low = limit(2, Side::SELL, 100, 5);
    Order mid = limit(3, Side::SELL, 101, 5);
    book.insert_order(high);
    book.insert_order(low);
    book.insert_order(mid);

    Order buy = limit(4, Side::BUY, 102, 5);
    book.insert_order(buy);
    EXPECT_FALSE(book.contains_order(2));  // price 100 filled
    EXPECT_TRUE(book.contains_order(1));
    EXPECT_TRUE(book.contains_order(3));
}

TEST(PriorityTest, SellHitsHighestBidFirst) {
    OrderBook book(10);
    Order low = limit(1, Side::BUY, 98, 5);
    Order high = limit(2, Side::BUY, 100, 5);
    Order mid = limit(3, Side::BUY, 99, 5);
    book.insert_order(low);
    book.insert_order(high);
    book.insert_order(mid);

    Order sell = limit(4, Side::SELL, 98, 5);
    book.insert_order(sell);
    EXPECT_FALSE(book.contains_order(2));  // price 100 filled
    EXPECT_TRUE(book.contains_order(1));
    EXPECT_TRUE(book.contains_order(3));
}

TEST(PriorityTest, NoMatchWhenPricesDoNotCross) {
    OrderBook book(10);
    Order sell = limit(1, Side::SELL, 101, 5);
    Order buy = limit(2, Side::BUY, 100, 5);
    book.insert_order(sell);
    book.insert_order(buy);
    EXPECT_TRUE(book.contains_order(1));
    EXPECT_TRUE(book.contains_order(2));
    EXPECT_EQ(book.get_order(1)->qty, 5u);
    EXPECT_EQ(book.get_order(2)->qty, 5u);
}

TEST(SweepTest, LimitBuySweepsMultipleLevelsAndRestsRemainder) {
    OrderBook book(10);
    Order a = limit(1, Side::SELL, 100, 3);
    Order b = limit(2, Side::SELL, 101, 3);
    Order c = limit(3, Side::SELL, 102, 3);
    Order d = limit(4, Side::SELL, 103, 3);
    book.insert_order(a);
    book.insert_order(b);
    book.insert_order(c);
    book.insert_order(d);

    Order buy = limit(5, Side::BUY, 102, 10);
    book.insert_order(buy);

    EXPECT_FALSE(book.contains_order(1));
    EXPECT_FALSE(book.contains_order(2));
    EXPECT_FALSE(book.contains_order(3));
    EXPECT_TRUE(book.contains_order(4));  // 103 is above the limit price
    ASSERT_TRUE(book.contains_order(5));
    EXPECT_EQ(book.get_order(5)->qty, 1u);  // 10 - 9 filled
}

TEST(SweepTest, LimitSellSweepsMultipleBidLevels) {
    OrderBook book(10);
    Order a = limit(1, Side::BUY, 100, 3);
    Order b = limit(2, Side::BUY, 99, 3);
    Order c = limit(3, Side::BUY, 98, 3);
    book.insert_order(a);
    book.insert_order(b);
    book.insert_order(c);

    Order sell = limit(4, Side::SELL, 99, 5);
    book.insert_order(sell);

    EXPECT_FALSE(book.contains_order(1));
    EXPECT_FALSE(book.contains_order(4));  // fully filled by 3 + 2
    ASSERT_TRUE(book.contains_order(2));
    EXPECT_EQ(book.get_order(2)->qty, 1u);
    EXPECT_TRUE(book.contains_order(3));
}

TEST(SweepTest, FullySweptLevelIsRemovedAndReusable) {
    OrderBook book(10);
    Order a = limit(1, Side::SELL, 100, 5);
    book.insert_order(a);
    Order buy = limit(2, Side::BUY, 100, 5);
    book.insert_order(buy);

    // the 100 ask level was emptied; a new ask there must work normally
    Order again = limit(3, Side::SELL, 100, 2);
    book.insert_order(again);
    ASSERT_TRUE(book.contains_order(3));
    EXPECT_EQ(book.get_order(3)->qty, 2u);
}

TEST(MarketOrderTest, SweepsLevelsAndDoesNotRestRemainder) {
    OrderBook book(10);
    Order a = limit(1, Side::SELL, 100, 3);
    Order b = limit(2, Side::SELL, 105, 3);
    book.insert_order(a);
    book.insert_order(b);

    Order m = market(3, Side::BUY, 10);
    book.insert_order(m);

    EXPECT_FALSE(book.contains_order(1));
    EXPECT_FALSE(book.contains_order(2));
    EXPECT_FALSE(book.contains_order(3));  // 4 unfilled, but market orders never rest
}

TEST(MarketOrderTest, PartiallyFillsRestingOrder) {
    OrderBook book(10);
    Order a = limit(1, Side::BUY, 100, 10);
    book.insert_order(a);

    Order m = market(2, Side::SELL, 4);
    book.insert_order(m);

    ASSERT_TRUE(book.contains_order(1));
    EXPECT_EQ(book.get_order(1)->qty, 6u);
    EXPECT_FALSE(book.contains_order(2));
}
