package dev.haotangyuan.researcher.interfaces.service;

import dev.haotangyuan.researcher.interfaces.dto.req.ConfirmDirectionReqDTO;
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

    /** HITL 方向确认：APPROVE 确认方向并继续，REVISE 修改方向重新分析 */
    SendMessageRespDTO confirmDirection(Long userId, String researchId, ConfirmDirectionReqDTO reqDTO);

    /** 取消研究中研究 */
    SendMessageRespDTO cancelResearch(Long userId, String researchId);
}
