package jp.stockai.app;

import static org.junit.Assert.assertEquals;

import java.net.URI;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;
import org.junit.Test;

public class MarketClientQueryTest {
    Map<String, String> parameters(String endpoint, String day, String cursor) throws Exception {
        URI uri = URI.create("https://api.jquants.com/v2" + endpoint + MarketClient.query(endpoint, day, cursor));
        Map<String, String> values = new HashMap<>();
        for (String pair : uri.getRawQuery().split("&")) {
            String[] parts = pair.split("=", 2);
            values.put(URLDecoder.decode(parts[0], StandardCharsets.UTF_8),
                URLDecoder.decode(parts[1], StandardCharsets.UTF_8));
        }
        return values;
    }

    @Test public void topixRequestsOnlyTheSelectedDayThroughItsSupportedRangeParameters() throws Exception {
        assertEquals(Map.of("from", "2026-10-19", "to", "2026-10-19"),
            parameters("/indices/bars/daily/topix", "2026-10-19", null));
    }

    @Test public void topixPaginationPreservesTheRangeAndOpaqueCursor() throws Exception {
        String cursor = "next.+/=& 日本語";
        assertEquals(Map.of("from", "2026-10-19", "to", "2026-10-19", "pagination_key", cursor),
            parameters("/indices/bars/daily/topix", "2026-10-19", cursor));
    }

    @Test public void calendarKeepsTheExistingPublicationWindowAcrossTheYearBoundary() throws Exception {
        assertEquals(Map.of("from", "2026-12-20", "to", "2027-01-10"),
            parameters("/markets/calendar", "2026-12-20", null));
    }

    @Test public void otherDateEndpointsKeepTheirSingleDayQueries() throws Exception {
        for (String endpoint : new String[]{"/equities/master", "/equities/bars/daily", "/fins/summary", "/equities/valuation"}) {
            assertEquals(Map.of("date", "2026-10-19"), parameters(endpoint, "2026-10-19", null));
        }
    }
}
