package dev.haotangyuan.researcher.interfaces.service;

import dev.haotangyuan.researcher.interfaces.dto.req.SendMessageReqDTO;
import dev.haotangyuan.researcher.interfaces.dto.resp.CreateResearchRespDTO;
import dev.haotangyuan.researcher.interfaces.dto.resp.ResearchMessageRespDTO;
import dev.haotangyuan.researcher.interfaces.dto.resp.ResearchStatusRespDTO;
import dev.haotangyuan.researcher.interfaces.dto.resp.SendMessageRespDTO;

import java.util.List;

/**
 * @author: haotangyuan
 */
public interface ResearchService {

    CreateResearchRespDTO createResearch(Long userId, Integer num);

    List<ResearchStatusRespDTO> getResearchList(Long userId);

    ResearchStatusRespDTO getResearchStatus(Long userId, String researchId);

    ResearchMessageRespDTO getResearchMessages(Long userId, String researchId);

    SendMessageRespDTO sendMessage(Long userId, String researchId, SendMessageReqDTO sendMessageReqDTO);
}
