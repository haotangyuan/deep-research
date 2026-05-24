package dev.haotangyuan.researcher.interfaces.dto.resp;

import lombok.Data;

/**
 * Google 用户信息响应
 * @author: haotangyuan
 */
@Data
public class GoogleUserInfoRespDTO {

    private String sub; //  OpenID (subject)，作为 googleId 存储
    private String aud; // 仅在 One Tap tokeninfo 场景下存在，用于校验 clientId
    private String email;
    private Boolean emailVerified;
    private String name;
    private String picture;
}
