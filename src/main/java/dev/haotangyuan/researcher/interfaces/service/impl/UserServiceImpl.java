package dev.haotangyuan.researcher.interfaces.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import dev.haotangyuan.researcher.domain.entity.User;
import dev.haotangyuan.researcher.domain.mapper.UserMapper;
import dev.haotangyuan.researcher.infra.exception.UserException;
import dev.haotangyuan.researcher.infra.util.JwtUtil;
import dev.haotangyuan.researcher.interfaces.dto.req.LoginReqDTO;
import dev.haotangyuan.researcher.interfaces.dto.req.RegisterReqDTO;
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

    private final UserMapper userMapper;
    private final JwtUtil jwtUtil;

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
    public UserInfoRespDTO getUserInfo(Long userId) {
        User user = userMapper.selectById(userId);
        if (user == null) {
            throw new UserException("用户不存在");
        }
        return UserInfoRespDTO.builder()
                .avatarUrl(user.getAvatarUrl())
                .build();
    }
}
