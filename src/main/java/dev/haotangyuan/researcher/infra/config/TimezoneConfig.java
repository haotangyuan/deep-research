package dev.haotangyuan.researcher.infra.config;

import com.fasterxml.jackson.datatype.jsr310.ser.LocalDateTimeSerializer;
import jakarta.annotation.PostConstruct;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.jackson.Jackson2ObjectMapperBuilderCustomizer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.TimeZone;

/**
 * 统一设置服务端 JSON 输出的默认时区
 * @author: haotangyuan
 */
@Configuration
public class TimezoneConfig {

    public static final String DEFAULT_ZONE_ID = "Asia/Shanghai";

    @Value("${app.time-zone:" + DEFAULT_ZONE_ID + "}")
    private String configuredZoneId;

    @PostConstruct
    public void alignSystemTimezone() {
        TimeZone zone = TimeZone.getTimeZone(configuredZoneId);
        TimeZone.setDefault(zone);
        System.setProperty("user.timezone", zone.getID());
    }

    @Bean
    public Jackson2ObjectMapperBuilderCustomizer jacksonTimezoneCustomizer() {
        ZoneId zoneId = ZoneId.of(configuredZoneId);
        // 输出带时区偏移的ISO格式，如 2024-12-05T08:30:00+08:00
        String offset = zoneId.getRules().getOffset(java.time.Instant.now()).toString();
        DateTimeFormatter offsetFormatter = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss'" + offset + "'");
        
        return builder -> builder
                .timeZone(TimeZone.getTimeZone(configuredZoneId))
                .serializers(new LocalDateTimeSerializer(offsetFormatter));
    }
}
