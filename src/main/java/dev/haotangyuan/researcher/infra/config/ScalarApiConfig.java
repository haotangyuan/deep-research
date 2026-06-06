package dev.haotangyuan.researcher.infra.config;

import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.GetMapping;

/**
 * Scalar API 文档配置
 * 提供现代化的 API 文档 UI
 */
@Controller
public class ScalarApiConfig {

    @GetMapping("/scalar")
    public String scalarUi() {
        return "redirect:/scalar.html";
    }

    @GetMapping("/scalar.html")
    public String scalarHtml() {
        return "forward:/scalar/index.html";
    }
}
