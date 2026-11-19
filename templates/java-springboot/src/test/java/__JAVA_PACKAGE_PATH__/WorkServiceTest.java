package __JAVA_PACKAGE__;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import java.util.Map;
import org.junit.jupiter.api.Test;

/** Unit tests for your business logic. Add a test per rule you add to process(). */
class WorkServiceTest {
    private final SimpleMeterRegistry registry = new SimpleMeterRegistry();
    private final WorkService work = new WorkService(registry);

    @Test
    void processesValidItem() {
        assertThat(work.record(() -> work.process(Map.of("id", "42")))).containsEntry("status", "processed");
        assertThat(registry.get("app.work.items").tag("outcome", "success").counter().count()).isEqualTo(1.0);
    }

    @Test
    void rejectsItemWithoutId() {
        assertThatThrownBy(() -> work.record(() -> work.process(Map.of()))).isInstanceOf(WorkService.RejectedException.class);
        assertThat(registry.get("app.work.items").tag("outcome", "rejected").counter().count()).isEqualTo(1.0);
    }
}
