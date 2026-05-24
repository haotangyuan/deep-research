package dev.haotangyuan.researcher.interfaces.service;

import dev.haotangyuan.researcher.domain.entity.Model;
import dev.haotangyuan.researcher.interfaces.dto.req.AddModelReqDTO;
import dev.haotangyuan.researcher.interfaces.dto.resp.ModelRespDTO;

import java.util.List;

/**
 * Model service interface
 * @author: haotangyuan
 */
public interface ModelService {
    
    List<ModelRespDTO> getAvailableModels(Long userId);
    
    String addCustomModel(Long userId, AddModelReqDTO req);
    
    void deleteCustomModel(Long userId, String modelId);
    
    Model getModelById(Long userId, String modelId);
}
