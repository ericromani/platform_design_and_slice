package __JAVA_PACKAGE__;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;
import org.springframework.web.servlet.HandlerMapping;

/** Emits http_requests_total{method,path,status}, the platform's HTTP metric contract. */
@Component
public class HttpMetricsFilter extends OncePerRequestFilter {
    private final MeterRegistry registry;

    public HttpMetricsFilter(MeterRegistry registry) {
        this.registry = registry;
    }

    private static final java.util.Set<String> CONTRACT_PATHS = java.util.Set.of("/healthz", "/readyz", "/metrics");

    /** Route template, or a fixed label: raw URIs would explode metric cardinality. */
    static String pathLabel(Object pattern, String uri) {
        if (pattern != null) {
            return pattern.toString();
        }
        return CONTRACT_PATHS.contains(uri) ? uri : "unmatched";
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        try {
            chain.doFilter(request, response);
        } finally {
            Object pattern = request.getAttribute(HandlerMapping.BEST_MATCHING_PATTERN_ATTRIBUTE);
            Counter.builder("http.requests")
                    .tag("method", request.getMethod())
                    .tag("path", pathLabel(pattern, request.getRequestURI()))
                    .tag("status", Integer.toString(response.getStatus()))
                    .register(registry)
                    .increment();
        }
    }
}
