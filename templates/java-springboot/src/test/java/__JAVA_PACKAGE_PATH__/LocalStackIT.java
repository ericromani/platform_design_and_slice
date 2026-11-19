package __JAVA_PACKAGE__;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import org.junit.jupiter.api.Test;

/**
 * Integration tests against LocalStack (failsafe runs *IT classes in `mvn verify`).
 * The central build provides a LocalStack service container. Locally:
 * LOCALSTACK_ENDPOINT=http://localhost:4566 ./mvnw verify -DskipUnitTests
 */
class LocalStackIT {
    @Test
    void localStackReachable() throws Exception {
        String endpoint = System.getenv("LOCALSTACK_ENDPOINT");
        assumeTrue(endpoint != null, "LOCALSTACK_ENDPOINT not set");
        // TODO: replace with your service's real flow using the AWS SDK v2 with
        // endpointOverride(URI.create(endpoint)) (e.g. send to your queue, assert the row).
        HttpResponse<String> resp = HttpClient.newHttpClient().send(
                HttpRequest.newBuilder(URI.create(endpoint + "/_localstack/health")).build(),
                HttpResponse.BodyHandlers.ofString());
        assertThat(resp.statusCode()).isEqualTo(200);
    }
}
