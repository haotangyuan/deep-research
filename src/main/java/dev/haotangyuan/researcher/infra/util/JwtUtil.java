package dev.haotangyuan.researcher.infra.util;

import cn.hutool.core.date.DateUtil;
import dev.haotangyuan.researcher.infra.config.JwtProp;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.util.Date;

/**
 * JWT 工具类
 * @author: haotangyuan
 */
@Component
@RequiredArgsConstructor
public class JwtUtil {

    private final JwtProp jwtProp;

    public String generate(Long userId) {
        SecretKey key = Keys.hmacShaKeyFor(jwtProp.getSecret().getBytes(StandardCharsets.UTF_8));
        Date now = DateUtil.date();
        return Jwts.builder()
                .subject(String.valueOf(userId))
                .issuedAt(now)
                .expiration(DateUtil.offsetMinute(now, jwtProp.getExpiration().intValue()))
                .signWith(key)
                .compact();
    }

    public Long decode(String token) {
        try {
            SecretKey key = Keys.hmacShaKeyFor(jwtProp.getSecret().getBytes(StandardCharsets.UTF_8));
            Claims claims = Jwts.parser()
                    .verifyWith(key)
                    .build()
                    .parseSignedClaims(token)
                    .getPayload();
            return Long.parseLong(claims.getSubject());
        } catch (Exception e) {
            return null;
        }
    }
}
