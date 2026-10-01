#include <nlohmann/json.hpp>
#include <string>
#include <vector>

std::string process_json(const std::string &text)
{
    nlohmann::json document = nlohmann::json::parse(text);
    std::vector<int> values = document.at("values").get<std::vector<int>>();
    long long total = 0;
    for (int value : values)
        total += value;
    document["sum"] = total;
    document["count"] = values.size();
    return document.dump();
}
