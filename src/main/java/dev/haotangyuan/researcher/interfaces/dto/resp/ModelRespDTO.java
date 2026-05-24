package dev.haotangyuan.researcher.interfaces.dto.resp;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * Model summary response DTO
 * @author: haotangyuan
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class ModelRespDTO {
    private String id;
    private String type;
    private String name;
    private String model;
    private String baseUrl;
}
