package dev.haotangyuan.researcher.interfaces.service.impl;

import cn.hutool.core.util.StrUtil;
import cn.hutool.http.HttpRequest;
import cn.hutool.http.HttpResponse;
import cn.hutool.json.JSONUtil;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import dev.haotangyuan.researcher.domain.entity.User;
import dev.haotangyuan.researcher.domain.mapper.UserMapper;
import dev.haotangyuan.researcher.infra.config.GoogleProp;
import dev.haotangyuan.researcher.infra.exception.UserException;
import dev.haotangyuan.researcher.infra.util.JwtUtil;
import dev.haotangyuan.researcher.interfaces.dto.req.GoogleOneTapReqDTO;
import dev.haotangyuan.researcher.interfaces.dto.req.LoginReqDTO;
import dev.haotangyuan.researcher.interfaces.dto.req.RegisterReqDTO;
import dev.haotangyuan.researcher.interfaces.dto.resp.GoogleUserInfoRespDTO;
import dev.haotangyuan.researcher.interfaces.dto.resp.LoginRespDTO;
import dev.haotangyuan.researcher.interfaces.dto.resp.UserInfoRespDTO;
import dev.haotangyuan.researcher.interfaces.service.UserService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;

/**
 * @author: haotangyuan
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class UserServiceImpl implements UserService {

    private final GoogleProp googleProp;
    private final UserMapper userMapper;
    private final JwtUtil jwtUtil;

    private static final String GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token";
    private static final String GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo";
    private static final String GOOGLE_TOKEN_INFO_URL = "https://oauth2.googleapis.com/tokeninfo";
    private static final String AVATAR_URL_TEMPLATE = "https://api.dicebear.com/9.x/pixel-art/svg?seed=%s";

    @Override
    public LoginRespDTO register(RegisterReqDTO req) {
        // 检查用户名是否已存在
        LambdaQueryWrapper<User> query = Wrappers.lambdaQuery(User.class)
                .eq(User::getUsername, req.getUsername());
        if (userMapper.selectOne(query) != null) {
            throw new UserException("用户名已存在");
        }

        User user = User.builder()
                .username(req.getUsername())
                .password(req.getPassword())
                .avatarUrl(String.format(AVATAR_URL_TEMPLATE, req.getUsername()))
                .createTime(LocalDateTime.now())
                .updateTime(LocalDateTime.now())
                .build();
        userMapper.insert(user);
        log.info("新用户注册: {}", user.getUsername());

        return LoginRespDTO.builder()
                .token(jwtUtil.generate(user.getId()))
                .build();
    }

    @Override
    public LoginRespDTO login(LoginReqDTO req) {
        LambdaQueryWrapper<User> query = Wrappers.lambdaQuery(User.class)
                .eq(User::getUsername, req.getUsername());
        User user = userMapper.selectOne(query);
        if (user == null) {
            throw new UserException("用户不存在");
        }
        if (user.getPassword() == null || !req.getPassword().equals(user.getPassword())) {
            throw new UserException("密码错误");
        }

        return LoginRespDTO.builder()
                .token(jwtUtil.generate(user.getId()))
                .build();
    }

    @Override
    public LoginRespDTO handleGoogleCallback(String code) {
        // 1. 换 token
        String accessToken = exchangeToken(code);
        // 2. 获取用户信息
        GoogleUserInfoRespDTO info = fetchUserInfo(accessToken);
        // 3. 查找或创建用户
        User user = findOrCreateGoogleUser(info);
        // 4. 生成 JWT
        return LoginRespDTO.builder()
                .token(jwtUtil.generate(user.getId()))
                .build();
    }

    @Override
    public LoginRespDTO handleGoogleOneTap(GoogleOneTapReqDTO req) {
        GoogleUserInfoRespDTO info = verifyIdToken(req.getCredential());
        User user = findOrCreateGoogleUser(info);
        return LoginRespDTO.builder()
                .token(jwtUtil.generate(user.getId()))
                .build();
    }

    @Override
    public UserInfoRespDTO getUserInfo(Long userId) {
        User user = userMapper.selectById(userId);
        if (user == null) {
            throw new UserException("用户不存在");
        }
        return UserInfoRespDTO.builder()
                .avatarUrl(user.getAvatarUrl())
                .build();
    }

    private String exchangeToken(String code) {
        HttpResponse resp = HttpRequest.post(GOOGLE_TOKEN_URL)
                .form("code", code)
                .form("client_id", googleProp.getClientId())
                .form("client_secret", googleProp.getClientSecret())
                .form("redirect_uri", googleProp.getRedirectUri())
                .form("grant_type", "authorization_code")
                .execute();

        if (!resp.isOk()) {
            log.error("Google token 交换失败: {}", resp.body());
            throw new UserException("Google 登录失败");
        }
        return JSONUtil.parseObj(resp.body()).getStr("access_token");
    }

    private GoogleUserInfoRespDTO verifyIdToken(String credential) {
        if (StrUtil.isBlank(credential)) {
            throw new UserException("Google 登录失败");
        }
        HttpResponse resp = HttpRequest.get(GOOGLE_TOKEN_INFO_URL)
                .form("id_token", credential)
                .execute();
        if (!resp.isOk()) {
            log.error("Google One Tap 校验失败: {}", resp.body());
            throw new UserException("Google 登录失败");
        }

        GoogleUserInfoRespDTO info = JSONUtil.toBean(resp.body(), GoogleUserInfoRespDTO.class);
        String aud = info.getAud();
        if (StrUtil.isNotBlank(googleProp.getClientId()) && !StrUtil.equals(googleProp.getClientId(), aud)) {
            log.error("Google One Tap aud 不匹配, expected={}, actual={}", googleProp.getClientId(), aud);
            throw new UserException("Google 登录失败");
        }

        if (StrUtil.isBlank(info.getSub())) {
            log.error("Google One Tap 响应缺少 sub: {}", resp.body());
            throw new UserException("Google 登录失败");
        }

        return info;
    }

    private GoogleUserInfoRespDTO fetchUserInfo(String accessToken) {
        HttpResponse resp = HttpRequest.get(GOOGLE_USERINFO_URL)
                .header("Authorization", "Bearer " + accessToken)
                .execute();
        if (!resp.isOk()) {
            log.error("获取 Google 用户信息失败: {}", resp.body());
            throw new UserException("获取 Google 用户信息失败");
        }
        return JSONUtil.toBean(resp.body(), GoogleUserInfoRespDTO.class);
    }

    private User findOrCreateGoogleUser(GoogleUserInfoRespDTO info) {
        LambdaQueryWrapper<User> query = Wrappers.lambdaQuery(User.class)
                .eq(User::getGoogleId, info.getSub());
        User user = userMapper.selectOne(query);

        if (user == null) {
            // Google 用户不设置 username，avatar 用 googleId 作为 seed
            user = User.builder()
                    .googleId(info.getSub())
                    .avatarUrl(String.format(AVATAR_URL_TEMPLATE, info.getSub()))
                    .createTime(LocalDateTime.now())
                    .updateTime(LocalDateTime.now())
                    .build();
            userMapper.insert(user);
            log.info("Google 新用户注册: googleId={}, userId={}", info.getSub(), user.getId());
        }
        return user;
    }
}
