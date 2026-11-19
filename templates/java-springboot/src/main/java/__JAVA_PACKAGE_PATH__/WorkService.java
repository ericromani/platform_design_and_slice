package __JAVA_PACKAGE__;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import java.util.Map;
import java.util.function.Supplier;
import org.springframework.stereotype.Service;

/**
 * Your service's unit of work. Replace {@link #process} with your logic.
 *
 * <p>Every item is reported through {@link #record} using the platform metric contract
 * (app_work_items_total{outcome}, app_work_duration_seconds) so the rollout analysis can
 * judge new releases and roll back a canary whose failure ratio is too high.
 */
@Service
public class WorkService {

    /** Bad input that retrying will never fix (outcome="rejected"). */
    public static class RejectedException extends RuntimeException {
        public RejectedException(String message) {
            super(message);
        }
    }

    private final Map<String, Counter> outcomes;
    private final Timer duration;

    public WorkService(MeterRegistry registry) {
        this.outcomes = Map.of(
                "success", counter(registry, "success"),
                "failure", counter(registry, "failure"),
                "rejected", counter(registry, "rejected"));
        this.duration = Timer.builder("app.work.duration").description("Time to process one work item.").register(registry);
    }

    private static Counter counter(MeterRegistry registry, String outcome) {
        return Counter.builder("app.work.items").description("Work items processed.").tag("outcome", outcome).register(registry);
    }

    /** TODO: implement your business logic. Throw RejectedException for invalid input. */
    public Map<String, String> process(Map<String, Object> item) {
        Object id = item.get("id");
        if (id == null || id.toString().isBlank()) {
            throw new RejectedException("item needs an id");
        }
        return Map.of("id", id.toString(), "status", "processed");
    }

    public <T> T record(Supplier<T> work) {
        String outcome = "failure";
        Timer.Sample sample = Timer.start();
        try {
            T result = work.get();
            outcome = "success";
            return result;
        } catch (RejectedException e) {
            outcome = "rejected";
            throw e;
        } finally {
            outcomes.get(outcome).increment();
            sample.stop(duration);
        }
    }
}
