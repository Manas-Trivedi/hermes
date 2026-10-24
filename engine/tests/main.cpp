#include <gtest/gtest.h>
#include <vector>
#include <matcha/order_book.hpp>

static Status try_insert(OrderBook &book, const Order &order, std::vector<Trade> &trades) {
    return book.insert_order(order, trades);
}

// For tests that expect the order to be accepted.
static std::vector<Trade> insert(OrderBook &book, const Order &order) {
    std::vector<Trade> trades;
    EXPECT_EQ(try_insert(book, order, trades), Status::Ok);
    return trades;
}

TEST(OrderBookTest, MarketOrderNeverRests) {
    OrderBook book(10);

    Order order;
    order.id = 1;
    order.side = Side::BUY;
    order.order_type = OrderType::MARKET;
    order.qty = 5;

    insert(book, order);
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
    insert(book, sell);
    Order c = cancel(1);
    insert(book, c);
    EXPECT_FALSE(book.contains_order(1));

    Order buy = limit(2, Side::BUY, 100, 5);
    insert(book, buy);
    EXPECT_TRUE(book.contains_order(2));
    EXPECT_EQ(book.get_order(2)->qty, 5u);
}

TEST(CancelTest, UnknownIdIsIgnored) {
    OrderBook book(10);
    Order o = limit(1, Side::BUY, 100, 5);
    insert(book, o);

    Order c = cancel(99);
    std::vector<Trade> trades;
    EXPECT_EQ(try_insert(book, c, trades), Status::UnknownId);
    EXPECT_TRUE(book.contains_order(1));
}

TEST(CancelTest, CancelMiddleOfLevelKeepsOthers) {
    OrderBook book(10);
    Order a = limit(1, Side::SELL, 100, 1);
    Order b = limit(2, Side::SELL, 100, 1);
    Order c = limit(3, Side::SELL, 100, 1);
    insert(book, a);
    insert(book, b);
    insert(book, c);

    Order x = cancel(2);
    insert(book, x);
    EXPECT_TRUE(book.contains_order(1));
    EXPECT_FALSE(book.contains_order(2));
    EXPECT_TRUE(book.contains_order(3));

    // the remaining two still fill in arrival order
    Order buy = limit(4, Side::BUY, 100, 1);
    insert(book, buy);
    EXPECT_FALSE(book.contains_order(1));
    EXPECT_TRUE(book.contains_order(3));
}

TEST(CancelTest, ArenaSlotIsReusedAfterCancel) {
    OrderBook book(1);
    Order a = limit(1, Side::BUY, 100, 5);
    insert(book, a);
    Order x = cancel(1);
    insert(book, x);

    Order b = limit(2, Side::BUY, 100, 5);
    insert(book, b);
    EXPECT_TRUE(book.contains_order(2));
}

TEST(PriorityTest, FifoWithinPriceLevel) {
    OrderBook book(10);
    Order first = limit(1, Side::SELL, 100, 5);
    Order second = limit(2, Side::SELL, 100, 5);
    insert(book, first);
    insert(book, second);

    Order buy = limit(3, Side::BUY, 100, 5);
    insert(book, buy);
    EXPECT_FALSE(book.contains_order(1));  // earlier order filled first
    EXPECT_TRUE(book.contains_order(2));
    EXPECT_EQ(book.get_order(2)->qty, 5u);
}

TEST(PriorityTest, FifoPartialFillKeepsQueuePosition) {
    OrderBook book(10);
    Order first = limit(1, Side::SELL, 100, 10);
    Order second = limit(2, Side::SELL, 100, 10);
    insert(book, first);
    insert(book, second);

    Order buy1 = limit(3, Side::BUY, 100, 4);
    insert(book, buy1);
    Order buy2 = limit(4, Side::BUY, 100, 4);
    insert(book, buy2);

    // order 1 absorbed both partial fills and is still ahead of order 2
    EXPECT_EQ(book.get_order(1)->qty, 2u);
    EXPECT_EQ(book.get_order(2)->qty, 10u);
}

TEST(PriorityTest, BuyHitsLowestAskFirst) {
    OrderBook book(10);
    Order high = limit(1, Side::SELL, 102, 5);
    Order low = limit(2, Side::SELL, 100, 5);
    Order mid = limit(3, Side::SELL, 101, 5);
    insert(book, high);
    insert(book, low);
    insert(book, mid);

    Order buy = limit(4, Side::BUY, 102, 5);
    insert(book, buy);
    EXPECT_FALSE(book.contains_order(2));  // price 100 filled
    EXPECT_TRUE(book.contains_order(1));
    EXPECT_TRUE(book.contains_order(3));
}

TEST(PriorityTest, SellHitsHighestBidFirst) {
    OrderBook book(10);
    Order low = limit(1, Side::BUY, 98, 5);
    Order high = limit(2, Side::BUY, 100, 5);
    Order mid = limit(3, Side::BUY, 99, 5);
    insert(book, low);
    insert(book, high);
    insert(book, mid);

    Order sell = limit(4, Side::SELL, 98, 5);
    insert(book, sell);
    EXPECT_FALSE(book.contains_order(2));  // price 100 filled
    EXPECT_TRUE(book.contains_order(1));
    EXPECT_TRUE(book.contains_order(3));
}

TEST(PriorityTest, NoMatchWhenPricesDoNotCross) {
    OrderBook book(10);
    Order sell = limit(1, Side::SELL, 101, 5);
    Order buy = limit(2, Side::BUY, 100, 5);
    insert(book, sell);
    insert(book, buy);
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
    insert(book, a);
    insert(book, b);
    insert(book, c);
    insert(book, d);

    Order buy = limit(5, Side::BUY, 102, 10);
    insert(book, buy);

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
    insert(book, a);
    insert(book, b);
    insert(book, c);

    Order sell = limit(4, Side::SELL, 99, 5);
    insert(book, sell);

    EXPECT_FALSE(book.contains_order(1));
    EXPECT_FALSE(book.contains_order(4));  // fully filled by 3 + 2
    ASSERT_TRUE(book.contains_order(2));
    EXPECT_EQ(book.get_order(2)->qty, 1u);
    EXPECT_TRUE(book.contains_order(3));
}

TEST(SweepTest, FullySweptLevelIsRemovedAndReusable) {
    OrderBook book(10);
    Order a = limit(1, Side::SELL, 100, 5);
    insert(book, a);
    Order buy = limit(2, Side::BUY, 100, 5);
    insert(book, buy);

    // the 100 ask level was emptied; a new ask there must work normally
    Order again = limit(3, Side::SELL, 100, 2);
    insert(book, again);
    ASSERT_TRUE(book.contains_order(3));
    EXPECT_EQ(book.get_order(3)->qty, 2u);
}

TEST(MarketOrderTest, SweepsLevelsAndDoesNotRestRemainder) {
    OrderBook book(10);
    Order a = limit(1, Side::SELL, 100, 3);
    Order b = limit(2, Side::SELL, 105, 3);
    insert(book, a);
    insert(book, b);

    Order m = market(3, Side::BUY, 10);
    insert(book, m);

    EXPECT_FALSE(book.contains_order(1));
    EXPECT_FALSE(book.contains_order(2));
    EXPECT_FALSE(book.contains_order(3));  // 4 unfilled, but market orders never rest
}

TEST(MarketOrderTest, PartiallyFillsRestingOrder) {
    OrderBook book(10);
    Order a = limit(1, Side::BUY, 100, 10);
    insert(book, a);

    Order m = market(2, Side::SELL, 4);
    insert(book, m);

    ASSERT_TRUE(book.contains_order(1));
    EXPECT_EQ(book.get_order(1)->qty, 6u);
    EXPECT_FALSE(book.contains_order(2));
}

TEST(TradeTest, TradeCarriesMakersPriceNotTakers) {
    OrderBook book(10);
    Order sell = limit(1, Side::SELL, 100, 5);
    insert(book, sell);

    Order buy = limit(2, Side::BUY, 101, 5);
    auto trades = insert(book, buy);

    ASSERT_EQ(trades.size(), 1u);
    EXPECT_EQ(trades[0].taker_id, 2u);
    EXPECT_EQ(trades[0].maker_id, 1u);
    EXPECT_EQ(trades[0].price, 100u);
    EXPECT_EQ(trades[0].qty, 5u);
}

TEST(TradeTest, SweepEmitsOneTradePerMakerInMatchOrder) {
    OrderBook book(10);
    Order a = limit(1, Side::SELL, 101, 3);
    Order b = limit(2, Side::SELL, 100, 3);
    Order c = limit(3, Side::SELL, 100, 3);
    insert(book, a);
    insert(book, b);
    insert(book, c);

    Order buy = limit(4, Side::BUY, 101, 8);
    auto trades = insert(book, buy);

    ASSERT_EQ(trades.size(), 3u);
    EXPECT_EQ(trades[0].maker_id, 2u);  // best price, earliest arrival
    EXPECT_EQ(trades[0].qty, 3u);
    EXPECT_EQ(trades[1].maker_id, 3u);
    EXPECT_EQ(trades[1].qty, 3u);
    EXPECT_EQ(trades[2].maker_id, 1u);  // next level
    EXPECT_EQ(trades[2].price, 101u);
    EXPECT_EQ(trades[2].qty, 2u);       // only what the taker had left
}

TEST(TradeTest, NoTradeWhenNothingCrosses) {
    OrderBook book(10);
    Order sell = limit(1, Side::SELL, 101, 5);
    insert(book, sell);
    Order buy = limit(2, Side::BUY, 100, 5);
    EXPECT_TRUE(insert(book, buy).empty());
}

TEST(TradeTest, MarketSellTradesAtRestingBidPrice) {
    OrderBook book(10);
    Order bid = limit(1, Side::BUY, 100, 10);
    insert(book, bid);

    Order m = market(2, Side::SELL, 4);
    auto trades = insert(book, m);

    ASSERT_EQ(trades.size(), 1u);
    EXPECT_EQ(trades[0].price, 100u);
    EXPECT_EQ(trades[0].qty, 4u);
}

TEST(StatusTest, DuplicateIdIsRejectedBeforeAnyMatching) {
    OrderBook book(10);
    Order sell = limit(1, Side::SELL, 100, 5);
    insert(book, sell);
    Order resting = limit(2, Side::BUY, 90, 5);
    insert(book, resting);

    // reuses id 2 and would cross the ask if it were allowed to match
    Order dup = limit(2, Side::BUY, 100, 5);
    std::vector<Trade> trades;
    EXPECT_EQ(try_insert(book, dup, trades), Status::DuplicateId);
    EXPECT_TRUE(trades.empty());
    EXPECT_EQ(book.get_order(1)->qty, 5u);
    EXPECT_EQ(book.get_order(2)->qty, 5u);
}

TEST(StatusTest, FullArenaRejectsNewRestingOrder) {
    OrderBook book(1);
    Order a = limit(1, Side::BUY, 100, 5);
    insert(book, a);

    Order b = limit(2, Side::BUY, 99, 5);
    std::vector<Trade> trades;
    EXPECT_EQ(try_insert(book, b, trades), Status::ArenaFull);
    EXPECT_FALSE(book.contains_order(2));
    EXPECT_TRUE(trades.empty());
}

TEST(StatusTest, CrossingOrderStillWorksWhenArenaIsFull) {
    OrderBook book(1);
    Order sell = limit(1, Side::SELL, 100, 2);
    insert(book, sell);  // arena is now full

    // trades 2, which frees the slot, and the remainder of 3 rests in it
    Order buy = limit(2, Side::BUY, 100, 5);
    auto trades = insert(book, buy);
    ASSERT_EQ(trades.size(), 1u);
    ASSERT_TRUE(book.contains_order(2));
    EXPECT_EQ(book.get_order(2)->qty, 3u);
}

TEST(InsertTest, CallersOrderIsNotModified) {
    OrderBook book(10);
    Order sell = limit(1, Side::SELL, 100, 4);
    insert(book, sell);

    Order buy = limit(2, Side::BUY, 100, 10);
    auto trades = insert(book, buy);

    EXPECT_EQ(buy.qty, 10u);               // untouched by matching
    ASSERT_EQ(trades.size(), 1u);
    EXPECT_EQ(trades[0].qty, 4u);
    ASSERT_TRUE(book.contains_order(2));
    EXPECT_EQ(book.get_order(2)->qty, 6u); // the resting remainder
}
