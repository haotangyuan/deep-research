package dev.haotangyuan.researcher.interfaces.controller;

import dev.haotangyuan.researcher.infra.common.Result;
import dev.haotangyuan.researcher.infra.common.Results;
import dev.haotangyuan.researcher.interfaces.dto.req.LoginReqDTO;
import dev.haotangyuan.researcher.interfaces.dto.req.RegisterReqDTO;
import dev.haotangyuan.researcher.interfaces.dto.resp.LoginRespDTO;
import dev.haotangyuan.researcher.interfaces.dto.resp.UserInfoRespDTO;
import dev.haotangyuan.researcher.interfaces.service.UserService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

/**
 * @author: haotangyuan
 */
@RestController
@RequiredArgsConstructor
public class UserController {

    private final UserService userService;

    @PostMapping("/api/v1/user/register")
    public Result<LoginRespDTO> register(@RequestBody RegisterReqDTO req) {
        return Results.success(userService.register(req));
    }

    @PostMapping("/api/v1/user/login")
    public Result<LoginRespDTO> login(@RequestBody LoginReqDTO req) {
        return Results.success(userService.login(req));
    }

    @GetMapping("/api/v1/user/me")
    public Result<UserInfoRespDTO> getCurrentUser(@RequestAttribute("userId") Long userId) {
        return Results.success(userService.getUserInfo(userId));
    }
}
