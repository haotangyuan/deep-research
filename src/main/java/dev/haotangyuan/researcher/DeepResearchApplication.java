package dev.haotangyuan.researcher;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.util.TimeZone;

@SpringBootApplication
@MapperScan("dev.haotangyuan.researcher.domain.mapper")
public class DeepResearchApplication {

    private static final String DEFAULT_ZONE_ID = "Asia/Shanghai";
    private static final String ENV_TIME_ZONE = "APP_TIME_ZONE";

    public static void main(String[] args) {
        TimeZone appTimeZone = resolveTimeZone();
        TimeZone.setDefault(appTimeZone);
        System.setProperty("user.timezone", appTimeZone.getID());
        SpringApplication.run(DeepResearchApplication.class, args);
    }

    private static TimeZone resolveTimeZone() {
        String envZone = System.getenv(ENV_TIME_ZONE);
        if (envZone == null || envZone.isBlank()) {
            envZone = System.getProperty("app.time-zone", DEFAULT_ZONE_ID);
        }
        return TimeZone.getTimeZone(envZone);
    }
}
