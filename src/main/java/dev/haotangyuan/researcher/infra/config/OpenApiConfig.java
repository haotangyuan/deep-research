package dev.haotangyuan.researcher.infra.config;

import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.info.Info;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class OpenApiConfig {

    @Bean
    public OpenAPI deepResearchOpenAPI() {
        return new OpenAPI()
                .info(new Info()
                        .title("Deep Research API")
                        .description("基于多智能体协作的自动化深度研究平台")
                        .version("1.0.0"));
    }
}
