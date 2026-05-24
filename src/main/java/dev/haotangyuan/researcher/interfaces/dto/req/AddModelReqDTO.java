package dev.haotangyuan.researcher.interfaces.dto.req;

import lombok.Data;

/**
 * Add model request DTO
 * @author: haotangyuan
 */
@Data
public class AddModelReqDTO {
    
    private String name;
    private String model;
    private String baseUrl;
    private String apiKey;
}
