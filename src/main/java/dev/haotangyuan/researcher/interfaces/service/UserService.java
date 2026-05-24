package dev.haotangyuan.researcher.interfaces.service;

import dev.haotangyuan.researcher.interfaces.dto.req.GoogleOneTapReqDTO;
import dev.haotangyuan.researcher.interfaces.dto.req.LoginReqDTO;
import dev.haotangyuan.researcher.interfaces.dto.req.RegisterReqDTO;
import dev.haotangyuan.researcher.interfaces.dto.resp.LoginRespDTO;
import dev.haotangyuan.researcher.interfaces.dto.resp.UserInfoRespDTO;

/**
 * @author: haotangyuan
 */
public interface UserService {

    LoginRespDTO register(RegisterReqDTO req);

    LoginRespDTO login(LoginReqDTO req);

    LoginRespDTO handleGoogleCallback(String code);

    LoginRespDTO handleGoogleOneTap(GoogleOneTapReqDTO req);

    UserInfoRespDTO getUserInfo(Long userId);
}
