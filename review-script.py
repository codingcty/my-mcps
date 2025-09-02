#!/usr/bin/env python3
"""
ENAAS配置文件Review工具 v2
用于检查enaas.json和test-api_secret.yml文件的格式和一致性
"""

import json
import yaml
import re
import sys
from typing import Dict, List, Tuple, Any
from pathlib import Path


class ENAASReviewerV2:
    def __init__(self, enaas_file: str, secret_file: str):
        self.enaas_file = Path(enaas_file)
        self.secret_file = Path(secret_file)
        self.enaas_data = None
        self.secret_data = None
        self.errors = []
        self.warnings = []

    def load_files(self) -> bool:
        """加载并解析两个文件"""
        success = True
        
        # 加载enaas.json
        try:
            with open(self.enaas_file, 'r', encoding='utf-8') as f:
                self.enaas_data = json.load(f)
        except json.JSONDecodeError as e:
            self.errors.append(f"enaas.json JSON格式错误: {e}")
            success = False
        except FileNotFoundError:
            self.errors.append(f"找不到文件: {self.enaas_file}")
            success = False
        except Exception as e:
            self.errors.append(f"读取enaas.json时发生错误: {e}")
            success = False

        # 加载test-api_secret.yml
        try:
            with open(self.secret_file, 'r', encoding='utf-8') as f:
                self.secret_data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            self.errors.append(f"test-api_secret.yml YAML格式错误: {e}")
            success = False
        except FileNotFoundError:
            self.errors.append(f"找不到文件: {self.secret_file}")
            success = False
        except Exception as e:
            self.errors.append(f"读取test-api_secret.yml时发生错误: {e}")
            success = False

        return success

    def check_enaas_structure(self) -> bool:
        """检查enaas.json的结构是否符合要求"""
        if not self.enaas_data:
            return False

        required_keys = ['keys', 'autoKeys', 'encodedKeys']
        for key in required_keys:
            if key not in self.enaas_data:
                self.errors.append(f"enaas.json缺少必需的键: {key}")
                return False

        # 检查TEST-APP是否存在
        if 'TEST-APP' not in self.enaas_data['keys']:
            self.errors.append("enaas.json中缺少TEST-APP配置")
            return False

        return True

    def check_encoded_keys_consistency(self) -> bool:
        """检查所有encodeKeys是否都存在于keys中"""
        if not self.enaas_data:
            return False

        success = True
        keys_data = self.enaas_data.get('keys', {})
        encoded_keys_data = self.enaas_data.get('encodedKeys', {})

        for app_name, secret_configs in encoded_keys_data.items():
            if app_name not in keys_data:
                self.errors.append(f"encodedKeys中的应用 {app_name} 在keys中不存在")
                success = False
                continue

            for secret_name, encoded_key_list in secret_configs.items():
                if secret_name not in keys_data[app_name]:
                    self.errors.append(f"encodedKeys中的secret {secret_name} 在keys中不存在")
                    success = False
                    continue

                for encoded_key in encoded_key_list:
                    if encoded_key not in keys_data[app_name][secret_name]:
                        self.errors.append(f"encodedKeys中的key {encoded_key} 在keys.{app_name}.{secret_name}中不存在")
                        success = False

        return success

    def check_secret_placeholders(self) -> bool:
        """检查secret.yml中的ENAAS_PLACEHOLDER是否与enaas.json一致"""
        if not self.enaas_data or not self.secret_data:
            return False

        success = True
        
        # 获取secret.yml中的所有内容
        secret_content = ""
        try:
            with open(self.secret_file, 'r', encoding='utf-8') as f:
                secret_content = f.read()
        except Exception as e:
            self.errors.append(f"无法读取secret.yml内容: {e}")
            return False

        # 1. 首先检查ENAAS_PLACEHOLDER标签的完整性
        if not self._check_enaas_placeholder_tags(secret_content):
            success = False

        # 2. 然后检查placeholder内容是否与enaas.json一致
        placeholder_pattern = r'<ENAAS_PLACEHOLDER>(.*?)<ENAAS_PLACEHOLDER>'
        placeholders = re.findall(placeholder_pattern, secret_content)
        
        for placeholder in placeholders:
            # 检查是否在enaas.json中存在
            found = False
            
            # 1. 首先检查是否在keys中 (格式: secretname_keyname)
            for app_name, app_config in self.enaas_data.get('keys', {}).items():
                if found:
                    break
                for secret_name, key_list in app_config.items():
                    if found:
                        break
                    for key_name in key_list:
                        expected_placeholder = f"{secret_name}_{key_name}"
                        if placeholder == expected_placeholder:
                            found = True
                            break

            # 2. 如果没有找到，检查是否在autoKeys中 (格式: keyname_value)
            if not found:
                for app_name, auto_configs in self.enaas_data.get('autoKeys', {}).items():
                    if found:
                        break
                    for key_name, value_list in auto_configs.items():
                        if found:
                            break
                        for value in value_list:
                            expected_placeholder = f"{key_name}_{value}"
                            if placeholder == expected_placeholder:
                                found = True
                                break

            if not found:
                self.errors.append(f"ENAAS_PLACEHOLDER '{placeholder}' 在enaas.json中未找到对应的配置")
                success = False

        return success

    def _check_enaas_placeholder_tags(self, secret_content: str) -> bool:
        """检查ENAAS_PLACEHOLDER标签的完整性"""
        success = True
        
        # 查找所有ENAAS_PLACEHOLDER标签
        all_tags = re.findall(r'<ENAAS_PLACEHOLDER>', secret_content)
        
        # 检查标签数量是否为偶数（开始和结束标签成对出现）
        if len(all_tags) % 2 != 0:
            self.errors.append(f"ENAAS_PLACEHOLDER标签数量不正确: 找到 {len(all_tags)} 个标签，应该是偶数")
            success = False
        
        # 检查是否有未闭合的标签
        lines = secret_content.split('\n')
        for line_num, line in enumerate(lines, 1):
            # 计算当前行中ENAAS_PLACEHOLDER标签的数量
            tags_in_line = line.count('<ENAAS_PLACEHOLDER>')
            if tags_in_line > 0:
                # 如果一行中有标签，检查是否成对出现
                if tags_in_line % 2 != 0:
                    self.errors.append(f"第 {line_num} 行: ENAAS_PLACEHOLDER标签不成对，找到 {tags_in_line} 个标签")
                    success = False
        
        return success

    def check_auto_keys_usage(self) -> bool:
        """检查autoKeys中定义的所有配置是否都在secret.yml中被使用"""
        if not self.enaas_data or not self.secret_data:
            return False

        success = True
        auto_keys_data = self.enaas_data.get('autoKeys', {})
        
        # 获取secret.yml中的所有内容
        secret_content = ""
        try:
            with open(self.secret_file, 'r', encoding='utf-8') as f:
                secret_content = f.read()
        except Exception as e:
            self.errors.append(f"无法读取secret.yml内容: {e}")
            return False

        for app_name, auto_configs in auto_keys_data.items():
            for key_name, value_list in auto_configs.items():
                for value in value_list:
                    expected_placeholder = f"{key_name}_{value}"
                    if expected_placeholder not in secret_content:
                        self.warnings.append(f"autoKeys中定义的配置 '{expected_placeholder}' 在secret.yml中未被使用")

        return True

    def run_review(self) -> Dict[str, Any]:
        """运行完整的review流程"""
        print("开始ENAAS配置文件Review v2...")
        print(f"检查文件: {self.enaas_file} 和 {self.secret_file}")
        print("-" * 50)

        # 加载文件
        if not self.load_files():
            print("❌ 文件加载失败")
            print("❌ 发现以下错误:")
            for error in self.errors:
                print(f"  - {error}")
            return {
                'success': False,
                'errors': self.errors,
                'warnings': self.warnings
            }

        # 检查enaas.json结构
        if not self.check_enaas_structure():
            print("❌ enaas.json结构检查失败")
        else:
            print("✅ enaas.json结构检查通过")

        # 检查encodedKeys一致性
        if not self.check_encoded_keys_consistency():
            print("❌ encodedKeys一致性检查失败")
        else:
            print("✅ encodedKeys一致性检查通过")

        # 检查secret.yml中的placeholder
        if not self.check_secret_placeholders():
            print("❌ secret.yml placeholder检查失败")
        else:
            print("✅ secret.yml placeholder检查通过")

        # 检查autoKeys使用情况
        if not self.check_auto_keys_usage():
            print("❌ autoKeys使用情况检查失败")
        else:
            print("✅ autoKeys使用情况检查通过")

        # 输出结果
        print("-" * 50)
        if self.errors:
            print("❌ 发现以下错误:")
            for error in self.errors:
                print(f"  - {error}")
        else:
            print("✅ 所有检查都通过了!")

        if self.warnings:
            print("⚠️  发现以下警告:")
            for warning in self.warnings:
                print(f"  - {warning}")

        print(f"\n总计: {len(self.errors)} 个错误, {len(self.warnings)} 个警告")
        
        return {
            'success': len(self.errors) == 0,
            'errors': self.errors,
            'warnings': self.warnings
        }


def main():
    """主函数"""
    if len(sys.argv) != 3:
        print("用法: python enaas_reviewer_v2.py <enaas.json路径> <test-api_secret.yml路径>")
        print("示例: python enaas_reviewer_v2.py enaas-details.json test-api_secret.yml")
        sys.exit(1)

    enaas_file = sys.argv[1]
    secret_file = sys.argv[2]

    reviewer = ENAASReviewerV2(enaas_file, secret_file)
    result = reviewer.run_review()

    if result['success']:
        print("\n🎉 Review完成，所有检查都通过了!")
        sys.exit(0)
    else:
        print(f"\n❌ Review完成，发现 {len(result['errors'])} 个错误")
        sys.exit(1)


if __name__ == "__main__":
    main()
