package dev.haotangyuan.researcher.interfaces.service;

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

    UserInfoRespDTO getUserInfo(Long userId);
}
