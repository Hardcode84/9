/* SPDX-License-Identifier: Apache-2.0 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <vulkan/vulkan.h>
#define VK(call)                                                                                   \
    do {                                                                                           \
        VkResult r = (call);                                                                       \
        if (r != VK_SUCCESS) {                                                                     \
            fprintf(stderr, "%s: %d\n", #call, (int)r);                                            \
            exit(1);                                                                               \
        }                                                                                          \
    } while (0)
int main(int argc, char **argv)
{
    VkInstance instance;
    VkInstanceCreateInfo ici = {.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO};
    VkApplicationInfo app = {.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO,
                             .apiVersion = VK_API_VERSION_1_2};
    uint32_t count = 1, family, memory_index;
    VkPhysicalDevice physical;
    VkDevice device;
    VkQueue queue;
    float priority = 1;
    VkDeviceQueueCreateInfo qci = {.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
                                   .queueCount = 1,
                                   .pQueuePriorities = &priority};
    VkPhysicalDeviceVulkan12Features features = {
        .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_FEATURES, .shaderInt8 = VK_TRUE};
    VkDeviceCreateInfo dci = {.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,
                              .pNext = &features,
                              .queueCreateInfoCount = 1,
                              .pQueueCreateInfos = &qci};
    VkQueueFamilyProperties families[64];
    VkPhysicalDeviceMemoryProperties properties;
    VkBuffer buffer;
    VkBufferCreateInfo bci = {.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
                              .size = 272,
                              .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT};
    VkMemoryRequirements requirements;
    VkMemoryAllocateInfo mai = {.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO};
    VkDeviceMemory memory;
    void *mapped;
    VkDescriptorSetLayoutBinding bindings[3] = {
        {.binding = 0,
         .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,
         .descriptorCount = 1,
         .stageFlags = VK_SHADER_STAGE_COMPUTE_BIT},
        {.binding = 1,
         .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,
         .descriptorCount = 1,
         .stageFlags = VK_SHADER_STAGE_COMPUTE_BIT},
        {.binding = 2,
         .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
         .descriptorCount = 1,
         .stageFlags = VK_SHADER_STAGE_COMPUTE_BIT}};
    VkDescriptorSetLayoutCreateInfo dlci = {.sType =
                                                VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO,
                                            .bindingCount = 3,
                                            .pBindings = bindings};
    VkDescriptorSetLayout layout;
    VkPipelineLayout pipeline_layout;
    VkPipelineLayoutCreateInfo plci = {.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO,
                                       .setLayoutCount = 1,
                                       .pSetLayouts = &layout};
    VkShaderModule module;
    VkShaderModuleCreateInfo smci = {.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};
    VkComputePipelineCreateInfo pci = {.sType = VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO};
    VkPipeline pipeline;
    VkDescriptorPoolSize pool_sizes[2] = {{VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 2},
                                          {VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, 1}};
    VkDescriptorPoolCreateInfo dpci = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO,
                                       .maxSets = 1,
                                       .poolSizeCount = 2,
                                       .pPoolSizes = pool_sizes};
    VkDescriptorPool pool;
    VkDescriptorSetAllocateInfo dsai = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO,
                                        .descriptorSetCount = 1,
                                        .pSetLayouts = &layout};
    VkDescriptorSet set;
    VkDescriptorBufferInfo dbi[2] = {{.offset = 0, .range = 16}, {.offset = 256, .range = 16}};
    VkDescriptorImageInfo image_info = {.imageLayout = VK_IMAGE_LAYOUT_GENERAL};
    VkWriteDescriptorSet writes[3] = {{.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET,
                                       .dstBinding = 0,
                                       .descriptorCount = 1,
                                       .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,
                                       .pBufferInfo = &dbi[0]},
                                      {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET,
                                       .dstBinding = 1,
                                       .descriptorCount = 1,
                                       .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,
                                       .pBufferInfo = &dbi[1]},
                                      {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET,
                                       .dstBinding = 2,
                                       .descriptorCount = 1,
                                       .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE,
                                       .pImageInfo = &image_info}};
    VkImage image;
    VkDeviceMemory image_memory;
    VkImageCreateInfo image_create = {.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO,
                                      .imageType = VK_IMAGE_TYPE_2D,
                                      .format = VK_FORMAT_R32_SFLOAT,
                                      .extent = {4, 1, 1},
                                      .mipLevels = 1,
                                      .arrayLayers = 1,
                                      .samples = VK_SAMPLE_COUNT_1_BIT,
                                      .tiling = VK_IMAGE_TILING_OPTIMAL,
                                      .usage = VK_IMAGE_USAGE_STORAGE_BIT};
    VkImageViewCreateInfo view_create = {
        .sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO,
        .viewType = VK_IMAGE_VIEW_TYPE_2D,
        .format = VK_FORMAT_R32_SFLOAT,
        .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1}};
    VkImageMemoryBarrier image_barrier = {
        .sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
        .dstAccessMask = VK_ACCESS_SHADER_READ_BIT | VK_ACCESS_SHADER_WRITE_BIT,
        .oldLayout = VK_IMAGE_LAYOUT_UNDEFINED,
        .newLayout = VK_IMAGE_LAYOUT_GENERAL,
        .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
        .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
        .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1}};
    VkCommandPoolCreateInfo cpci = {.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO};
    VkCommandPool command_pool;
    VkCommandBufferAllocateInfo cbai = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
                                        .level = VK_COMMAND_BUFFER_LEVEL_PRIMARY,
                                        .commandBufferCount = 1};
    VkCommandBuffer commands;
    VkCommandBufferBeginInfo begin = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
    VkMemoryBarrier barrier = {.sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER,
                               .srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT,
                               .dstAccessMask = VK_ACCESS_HOST_READ_BIT};
    VkSubmitInfo submit = {.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO,
                           .commandBufferCount = 1,
                           .pCommandBuffers = &commands};
    FILE *file;
    long size;
    uint32_t *code;
    const float input[] = {1, 2, 3, 4};
    uint32_t expected[8];
    int status;
    if (argc != 3)
        return 2;
    file = fopen(argv[2], "rb");
    if (!file || fread(expected, sizeof(expected), 1, file) != 1 || fclose(file))
        return 2;
    file = fopen(argv[1], "rb");
    if (!file || fseek(file, 0, SEEK_END))
        return 2;
    size = ftell(file);
    if (size <= 0 || size % 4 || fseek(file, 0, SEEK_SET))
        return 2;
    code = malloc((size_t)size);
    if (!code || fread(code, 1, (size_t)size, file) != (size_t)size || fclose(file))
        return 2;
    ici.pApplicationInfo = &app;
    VK(vkCreateInstance(&ici, NULL, &instance));
    {
        VkResult result = vkEnumeratePhysicalDevices(instance, &count, &physical);
        /* The test requests one device. More available devices are permitted. */
        if ((result != VK_SUCCESS && result != VK_INCOMPLETE) || count == 0) {
            fprintf(stderr, "vkEnumeratePhysicalDevices: %d, count %u\n", (int)result,
                    (unsigned)count);
            return 1;
        }
    }
    count = 64;
    vkGetPhysicalDeviceQueueFamilyProperties(physical, &count, families);
    for (family = 0; family < count; ++family)
        if (families[family].queueFlags & VK_QUEUE_COMPUTE_BIT)
            break;
    if (family == count)
        return 2;
    {
        VkPhysicalDeviceFloatControlsProperties controls = {
            .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FLOAT_CONTROLS_PROPERTIES};
        VkPhysicalDeviceProperties2 props = {
            .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2, .pNext = &controls};
        VkPhysicalDeviceVulkan12Features support = {
            .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_FEATURES};
        VkPhysicalDeviceFeatures2 query = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2,
                                           .pNext = &support};
        vkGetPhysicalDeviceProperties2(physical, &props);
        vkGetPhysicalDeviceFeatures2(physical, &query);
        if (!support.shaderInt8 || !controls.shaderRoundingModeRTEFloat32 ||
            !controls.shaderSignedZeroInfNanPreserveFloat32 ||
            props.properties.limits.minStorageBufferOffsetAlignment > 256) {
            fputs("Vulkan device does not meet the shader profile\n", stderr);
            return 2;
        }
    }
    qci.queueFamilyIndex = family;
    VK(vkCreateDevice(physical, &dci, NULL, &device));
    vkGetDeviceQueue(device, family, 0, &queue);
    VK(vkCreateBuffer(device, &bci, NULL, &buffer));
    vkGetBufferMemoryRequirements(device, buffer, &requirements);
    vkGetPhysicalDeviceMemoryProperties(physical, &properties);
    for (memory_index = 0; memory_index < properties.memoryTypeCount; ++memory_index) {
        VkMemoryPropertyFlags flags =
            VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
        if ((requirements.memoryTypeBits & (1u << memory_index)) &&
            (properties.memoryTypes[memory_index].propertyFlags & flags) == flags)
            break;
    }
    if (memory_index == properties.memoryTypeCount)
        return 2;
    mai.allocationSize = requirements.size;
    mai.memoryTypeIndex = memory_index;
    VK(vkAllocateMemory(device, &mai, NULL, &memory));
    VK(vkBindBufferMemory(device, buffer, memory, 0));
    VK(vkMapMemory(device, memory, 0, requirements.size, 0, &mapped));
    memset(mapped, 0xff, 272);
    memcpy(mapped, input, sizeof(input));
    VK(vkCreateImage(device, &image_create, NULL, &image));
    vkGetImageMemoryRequirements(device, image, &requirements);
    for (memory_index = 0; memory_index < properties.memoryTypeCount; ++memory_index)
        if (requirements.memoryTypeBits & (1u << memory_index))
            break;
    if (memory_index == properties.memoryTypeCount)
        return 2;
    mai.allocationSize = requirements.size;
    mai.memoryTypeIndex = memory_index;
    VK(vkAllocateMemory(device, &mai, NULL, &image_memory));
    VK(vkBindImageMemory(device, image, image_memory, 0));
    view_create.image = image;
    VK(vkCreateImageView(device, &view_create, NULL, &image_info.imageView));
    VK(vkCreateDescriptorSetLayout(device, &dlci, NULL, &layout));
    VK(vkCreatePipelineLayout(device, &plci, NULL, &pipeline_layout));
    smci.codeSize = (size_t)size;
    smci.pCode = code;
    VK(vkCreateShaderModule(device, &smci, NULL, &module));
    free(code);
    pci.stage.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    pci.stage.stage = VK_SHADER_STAGE_COMPUTE_BIT;
    pci.stage.module = module;
    pci.stage.pName = "main";
    pci.layout = pipeline_layout;
    VK(vkCreateComputePipelines(device, VK_NULL_HANDLE, 1, &pci, NULL, &pipeline));
    VK(vkCreateDescriptorPool(device, &dpci, NULL, &pool));
    dsai.descriptorPool = pool;
    VK(vkAllocateDescriptorSets(device, &dsai, &set));
    dbi[0].buffer = buffer;
    dbi[1].buffer = buffer;
    writes[0].dstSet = set;
    writes[1].dstSet = set;
    writes[2].dstSet = set;
    vkUpdateDescriptorSets(device, 3, writes, 0, NULL);
    cpci.queueFamilyIndex = family;
    VK(vkCreateCommandPool(device, &cpci, NULL, &command_pool));
    cbai.commandPool = command_pool;
    VK(vkAllocateCommandBuffers(device, &cbai, &commands));
    VK(vkBeginCommandBuffer(commands, &begin));
    image_barrier.image = image;
    vkCmdPipelineBarrier(commands, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,
                         VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, 0, 0, NULL, 0, NULL, 1,
                         &image_barrier);
    vkCmdBindPipeline(commands, VK_PIPELINE_BIND_POINT_COMPUTE, pipeline);
    vkCmdBindDescriptorSets(commands, VK_PIPELINE_BIND_POINT_COMPUTE, pipeline_layout, 0, 1, &set,
                            0, NULL);
    vkCmdDispatch(commands, 1, 1, 1);
    vkCmdPipelineBarrier(commands, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_HOST_BIT,
                         0, 1, &barrier, 0, NULL, 0, NULL);
    VK(vkEndCommandBuffer(commands));
    VK(vkQueueSubmit(queue, 1, &submit, VK_NULL_HANDLE));
    VK(vkQueueWaitIdle(queue));
    status =
        memcmp(mapped, expected, 16) != 0 || memcmp((char *)mapped + 256, expected + 4, 16) != 0;
    printf("result: %.1f %.1f %.1f %.1f\n", (double)((float *)mapped)[0],
           (double)((float *)mapped)[1], (double)((float *)mapped)[2],
           (double)((float *)mapped)[3]);
    if (status) {
        const uint32_t *codes = (const uint32_t *)((const char *)mapped + 256);
        fprintf(stderr, "status: %u %u %u %u\n", codes[0], codes[1], codes[2], codes[3]);
    }
    vkDestroyImageView(device, image_info.imageView, NULL);
    vkDestroyImage(device, image, NULL);
    vkFreeMemory(device, image_memory, NULL);
    vkDestroyCommandPool(device, command_pool, NULL);
    vkDestroyDescriptorPool(device, pool, NULL);
    vkDestroyPipeline(device, pipeline, NULL);
    vkDestroyShaderModule(device, module, NULL);
    vkDestroyPipelineLayout(device, pipeline_layout, NULL);
    vkDestroyDescriptorSetLayout(device, layout, NULL);
    vkUnmapMemory(device, memory);
    vkDestroyBuffer(device, buffer, NULL);
    vkFreeMemory(device, memory, NULL);
    vkDestroyDevice(device, NULL);
    vkDestroyInstance(instance, NULL);
    return status;
}
