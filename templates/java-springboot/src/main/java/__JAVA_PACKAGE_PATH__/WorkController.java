package __JAVA_PACKAGE__;

import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class WorkController {
    private final WorkService work;

    public WorkController(WorkService work) {
        this.work = work;
    }

    @PostMapping("/work")
    public Map<String, String> work(@RequestBody Map<String, Object> item) {
        return work.record(() -> work.process(item));
    }

    @ExceptionHandler(WorkService.RejectedException.class)
    @ResponseStatus(HttpStatus.UNPROCESSABLE_CONTENT)
    public Map<String, String> rejected(WorkService.RejectedException e) {
        return Map.of("error", e.getMessage());
    }
}
