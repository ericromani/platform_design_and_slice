package __JAVA_PACKAGE__;

import static org.assertj.core.api.Assertions.assertThat;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;

/** Platform contract tests: probes and metrics must keep working. Keep these. */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class ContractTest {
    @LocalServerPort
    int port;

    private final HttpClient http = HttpClient.newHttpClient();

    private HttpResponse<String> get(String path) throws Exception {
        return http.send(HttpRequest.newBuilder(URI.create("http://localhost:" + port + path)).build(),
                HttpResponse.BodyHandlers.ofString());
    }

    @Test
    void probesAreServed() throws Exception {
        assertThat(get("/healthz").statusCode()).isEqualTo(200);
        assertThat(get("/readyz").statusCode()).isEqualTo(200);
    }

    @Test
    void metricsFollowPlatformContract() throws Exception {
        http.send(HttpRequest.newBuilder(URI.create("http://localhost:" + port + "/work"))
                        .header("Content-Type", "application/json")
                        .POST(HttpRequest.BodyPublishers.ofString("{\"id\":\"1\"}")).build(),
                HttpResponse.BodyHandlers.ofString());
        String body = get("/metrics").body();
        assertThat(body).contains("http_requests_total{method=\"POST\",path=\"/work\",status=\"200\"}");
        assertThat(body).contains("app_work_items_total{outcome=\"success\"}");
        assertThat(body).contains("app_work_duration_seconds_bucket");
    }
}
