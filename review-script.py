#!/usr/bin/env python3
"""
ENAAS配置文件Review工具 v2
用于检查enaas.json、*_secret.yml和*_dc.yml文件的格式和一致性

支持两种模式：
1. 手动指定文件路径
2. 自动扫描openshift文件夹 (使用命令: review openshift manifest)
"""

import json
import yaml
import re
import sys
import os
from typing import Dict, List, Tuple, Any, Optional
from pathlib import Path
from dataclasses import dataclass


@dataclass
class FileError:
    """文件错误信息"""
    file_name: str
    line_number: int
    char_position: int
    description: str
    
    def __str__(self):
        return f"{self.file_name}/第{self.line_number}行/第{self.char_position}个字符/{self.description}"


@dataclass
class SecretKeyError:
    """Secret Key错误信息"""
    file_name: str
    line_number: int
    char_position: int
    secret_name: str
    secret_key: str
    description: str
    
    def __str__(self):
        return f"{self.file_name}/第{self.line_number}行/第{self.char_position}个字符/{self.secret_name}.{self.secret_key}/{self.description}"


@dataclass
class ReviewResult:
    """检查结果数据类"""
    file_errors: List[FileError]
    secret_key_errors: List[SecretKeyError]
    placeholder_count: int
    secret_ref_match: bool
    secret_ref_names: Tuple[str, str]
    
    @property
    def has_errors(self) -> bool:
        return len(self.file_errors) > 0 or len(self.secret_key_errors) > 0
    
    @property
    def total_errors(self) -> int:
        return len(self.file_errors) + len(self.secret_key_errors)


class ENAASReviewerV2:
    """ENAAS配置文件Review工具主类"""
    
    def __init__(self, enaas_file: str, secret_file: str, dc_file: Optional[str] = None):
        self.enaas_file = Path(enaas_file)
        self.secret_file = Path(secret_file)
        self.dc_file = Path(dc_file) if dc_file else None
        
        # 文件数据
        self.enaas_data: Optional[Dict] = None
        self.secret_data: Optional[Dict] = None
        self.dc_data: Optional[Dict] = None
        
        # 检查结果
        self.result = ReviewResult(
            file_errors=[],
            secret_key_errors=[],
            placeholder_count=0,
            secret_ref_match=False,
            secret_ref_names=("", "")
        )
        
        # 验证文件命名规范
        self._validate_file_naming_convention()

    def _scan_openshift_directories(self, target_directory: Optional[str] = None) -> List[Tuple[Path, Path, Optional[Path]]]:
        """通用递归扫描，找到所有需要检查的文件组合"""
        current_dir = Path.cwd()
        
        if target_directory:
            # 指定目录扫描模式：从根目录开始寻找目标目录
            print(f"🔍 从根目录开始寻找目录: {target_directory}")
            target_path = self._find_directory_recursively(current_dir, target_directory)
            
            if not target_path:
                print(f"❌ 在根目录下未找到名为 '{target_directory}' 的目录")
                print("💡 提示：请检查目录名称是否正确，或使用 'review openshift manifest' 查看所有可用目录")
                return []
            
            print(f"🎯 找到目标目录: {target_path.relative_to(current_dir)}")
            print(f"🔍 开始扫描该目录下的所有内容...")
            scan_root = target_path
        else:
            # 全目录扫描模式
            print("🔍 开始通用递归扫描...")
            scan_root = current_dir
        
        file_combinations = []
        scanned_dirs = set()  # 避免重复扫描
        
        def scan_directory_recursive(directory: Path, depth: int = 0) -> None:
            """递归扫描目录，查找配置文件组合"""
            if depth > 10:  # 防止无限递归
                return
                
            if directory in scanned_dirs:
                return
                
            scanned_dirs.add(directory)
            
            # 检查当前目录是否包含配置文件
            enaas_files = list(directory.glob('*.json'))
            secret_files = list(directory.glob('*_secret.yml')) + list(directory.glob('*_secret.yaml'))
            dc_files = list(directory.glob('*_dc.yml')) + list(directory.glob('*_dc.yaml'))
            
            # 查找enaas文件
            enaas_file = None
            for file in enaas_files:
                if 'enaas' in file.name.lower():
                    enaas_file = file
                    break
            
            # 如果找到enaas文件，检查当前目录的完整性
            if enaas_file:
                # 显示相对路径（相对于扫描根目录）
                relative_path = directory.relative_to(scan_root)
                if relative_path == Path('.'):
                    display_path = scan_root.name if target_directory else "当前目录"
                else:
                    display_path = f"{scan_root.name}/{relative_path}" if target_directory else str(relative_path)
                
                print(f"\n📁 发现配置目录: {display_path}")
                
                # 查找secret文件
                secret_file = None
                if secret_files:
                    secret_file = secret_files[0]  # 取第一个找到的
                
                # 查找dc文件
                dc_file = None
                if dc_files:
                    dc_file = dc_files[0]  # 取第一个找到的
                
                # 检查是否找到必要的文件
                if secret_file:
                    print(f"   ✅ 找到文件组合:")
                    print(f"      - ENAAS: {enaas_file.name}")
                    print(f"      - Secret: {secret_file.name}")
                    if dc_file:
                        print(f"      - DC: {dc_file.name}")
                    else:
                        print(f"      - DC: 未找到")
                    
                    file_combinations.append((enaas_file, secret_file, dc_file))
                else:
                    print(f"   ⚠️  缺少secret文件")
                    print(f"      - ENAAS: {enaas_file.name}")
                    print(f"      - 需要: *_secret.yml 或 *_secret.yaml")
            
            # 递归扫描子目录
            try:
                for item in directory.iterdir():
                    if item.is_dir() and not item.name.startswith('.'):
                        scan_directory_recursive(item, depth + 1)
            except PermissionError:
                # 跳过无权限的目录
                pass
        
        # 开始递归扫描
        scan_directory_recursive(scan_root)
        
        if not file_combinations:
            if target_directory:
                print(f"❌ 在指定目录 {target_directory} 中未找到任何有效的配置文件组合")
            else:
                print("❌ 未找到任何有效的配置文件组合")
            print("💡 提示：确保目录中包含以下文件：")
            print("   - enaas-details.json 或包含'enaas'的.json文件")
            print("   - *_secret.yml 或 *_secret.yaml 文件")
            print("   - *_dc.yml 或 *_dc.yaml 文件（可选）")
        else:
            if target_directory:
                print(f"\n📊 扫描完成，在 {target_directory} 目录中找到 {len(file_combinations)} 个有效的文件组合")
            else:
                print(f"\n📊 扫描完成，找到 {len(file_combinations)} 个有效的文件组合")
        
        return file_combinations
    
    def _find_directory_recursively(self, root_dir: Path, target_name: str, depth: int = 0) -> Optional[Path]:
        """递归查找指定名称的目录"""
        if depth > 10:  # 防止无限递归
            return None
        
        # 检查当前目录
        if root_dir.name == target_name:
            return root_dir
        
        # 递归搜索子目录
        try:
            for item in root_dir.iterdir():
                if item.is_dir() and not item.name.startswith('.'):
                    result = self._find_directory_recursively(item, target_name, depth + 1)
                    if result:
                        return result
        except PermissionError:
            # 跳过无权限的目录
            pass
        
        return None

    def run_batch_review(self, target_directory: Optional[str] = None) -> List[ReviewResult]:
        """批量检查所有找到的文件组合"""
        if target_directory:
            print(f"🚀 开始批量检查指定目录: {target_directory}")
        else:
            print("🚀 开始批量检查所有openshift配置...")
        print("=" * 80)
        
        file_combinations = self._scan_openshift_directories(target_directory)
        if not file_combinations:
            print("❌ 没有找到需要检查的文件组合")
            return []
        
        results = []
        total_combinations = len(file_combinations)
        
        for i, (enaas_file, secret_file, dc_file) in enumerate(file_combinations, 1):
            print(f"\n{'='*20} 检查组合 {i}/{total_combinations} {'='*20}")
            print(f"📍 位置: {enaas_file.parent.relative_to(Path.cwd())}")
            
            # 创建新的reviewer实例
            reviewer = ENAASReviewerV2(str(enaas_file), str(secret_file), str(dc_file) if dc_file else None)
            
            # 运行检查
            try:
                result = reviewer.run_review()
                results.append(result)
                
                # 显示简要结果
                if result.has_errors:
                    print(f"❌ 组合 {i} 发现问题: {result.total_errors} 个")
                else:
                    print(f"✅ 组合 {i} 检查通过")
                    
            except Exception as e:
                print(f"❌ 组合 {i} 检查失败: {e}")
                # 创建错误结果
                error_result = ReviewResult(
                    file_errors=[FileError(
                        file_name=f"组合{i}",
                        line_number=0,
                        char_position=0,
                        description=f"检查失败: {e}"
                    )],
                    secret_key_errors=[],
                    placeholder_count=0,
                    secret_ref_match=False,
                    secret_ref_names=("", "")
                )
                results.append(error_result)
        
        # 显示批量检查总结
        self._print_batch_summary(results)
        
        return results

    def _print_batch_summary(self, results: List[ReviewResult]):
        """显示批量检查总结"""
        print(f"\n{'='*80}")
        print("📊 批量检查总结")
        print(f"{'='*80}")
        
        total_combinations = len(results)
        successful_combinations = sum(1 for r in results if not r.has_errors)
        failed_combinations = total_combinations - successful_combinations
        
        print(f"总检查组合数: {total_combinations}")
        print(f"✅ 成功: {successful_combinations}")
        print(f"❌ 失败: {failed_combinations}")
        
        if failed_combinations > 0:
            print(f"\n❌ 有问题的组合:")
            for i, result in enumerate(results, 1):
                if result.has_errors:
                    print(f"  组合 {i}: {result.total_errors} 个问题")
        else:
            print(f"\n🎉 所有组合检查都通过了!")

    def _validate_file_naming_convention(self):
        """验证文件命名规范"""
        # 检查enaas.json文件
        if not self.enaas_file.name.endswith('.json'):
            self.result.file_errors.append(FileError(
                file_name=self.enaas_file.name,
                line_number=0,
                char_position=0,
                description="enaas配置文件应该以.json结尾"
            ))
        
        # 检查secret文件命名规范
        if not self.secret_file.name.endswith('_secret.yml') and not self.secret_file.name.endswith('_secret.yaml'):
            self.result.file_errors.append(FileError(
                file_name=self.secret_file.name,
                line_number=0,
                char_position=0,
                description="secret文件应该以_secret.yml或_secret.yaml结尾"
            ))
        
        # 检查dc文件命名规范（如果提供）
        if self.dc_file:
            if not self.dc_file.name.endswith('_dc.yml') and not self.dc_file.name.endswith('_dc.yaml'):
                self.result.file_errors.append(FileError(
                    file_name=self.dc_file.name,
                    line_number=0,
                    char_position=0,
                    description="dc文件应该以_dc.yml或_dc.yaml结尾"
                ))
            
            # 检查secret和dc文件的基础名称是否一致
            secret_base = self.secret_file.name.replace('_secret.yml', '').replace('_secret.yaml', '')
            dc_base = self.dc_file.name.replace('_dc.yml', '').replace('_dc.yaml', '')
            
            if secret_base != dc_base:
                self.result.file_errors.append(FileError(
                    file_name=self.dc_file.name,
                    line_number=0,
                    char_position=0,
                    description=f"dc文件基础名称({dc_base})与secret文件基础名称({secret_base})不匹配"
                ))

    def run_review(self) -> ReviewResult:
        """运行完整的review流程"""
        print("开始ENAAS配置文件Review v2...")
        print(f"检查文件: {self.enaas_file} 和 {self.secret_file}")
        if self.dc_file:
            print(f"包含dc文件: {self.dc_file}")
        print("-" * 60)

        # 1. 检查各文件合法性（格式、结构、缩进）
        self._check_files_validity()
        
        # 2. 检查Secret Manifest合法性（placeholder）
        self._check_secret_manifest_validity()
        
        # 3. 检查secret匹配
        self._check_secret_matching()
        
        # 4. 检查secret引用合法性
        self._check_secret_reference_validity()
        
        # 输出结果
        self._print_results()
        
        return self.result

    def _check_files_validity(self):
        """1. 检查各文件合法性（格式、结构、缩进）"""
        print("1. 各文件合法性检查")
        print("   检查文件:", end=" ")
        
        files_to_check = [self.enaas_file, self.secret_file]
        if self.dc_file:
            files_to_check.append(self.dc_file)
        
        file_names = [f.name for f in files_to_check]
        print(", ".join(file_names))
        
        for file_path in files_to_check:
            self._validate_single_file(file_path)
        
        if self.result.file_errors:
            print("   ❌ 发现问题:")
            for error in self.result.file_errors:
                print(f"     - {error}")
        else:
            print("   ✅ 所有文件格式、结构、缩进都正确")

    def _validate_single_file(self, file_path: Path):
        """验证单个文件的合法性"""
        try:
            # 检查文件基本属性
            self._validate_file_basics(file_path)
            
            # 根据文件类型进行特定检查
            if file_path.suffix == '.json':
                self._validate_json_file(file_path)
            elif file_path.suffix in ['.yml', '.yaml']:
                self._validate_yaml_file(file_path)
                
        except Exception as e:
            self.result.file_errors.append(FileError(
                file_name=file_path.name,
                line_number=0,
                char_position=0,
                description=f"文件加载失败: {e}"
            ))

    def _validate_file_basics(self, file_path: Path):
        """验证文件基本属性"""
        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在")
            
        # 检查文件大小
        file_size = file_path.stat().st_size
        if file_size == 0:
            self.result.file_errors.append(FileError(
                file_name=file_path.name,
                line_number=0,
                char_position=0,
                description="文件为空"
            ))

    def _validate_json_file(self, file_path: Path):
        """验证JSON文件"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                self.enaas_data = json.loads(content)
        except json.JSONDecodeError as e:
            # 计算错误位置
            line_no, char_pos = self._calculate_json_error_position(content, e.pos)
            self.result.file_errors.append(FileError(
                file_name=file_path.name,
                line_number=line_no,
                char_position=char_pos,
                description=f"JSON格式错误: {e.msg}"
            ))

    def _validate_yaml_file(self, file_path: Path):
        """验证YAML文件"""
        try:
            # 检查YAML缩进
            self._validate_yaml_indentation(file_path)
            
            # 解析YAML
            with open(file_path, 'r', encoding='utf-8') as f:
                if file_path == self.secret_file:
                    self.secret_data = yaml.safe_load(f)
                elif file_path == self.dc_file:
                    self.dc_data = yaml.safe_load(f)
                    
        except yaml.YAMLError as e:
            # 计算错误位置
            line_no, char_pos = self._calculate_yaml_error_position(file_path, e)
            self.result.file_errors.append(FileError(
                file_name=file_path.name,
                line_number=line_no,
                char_position=char_pos,
                description=f"YAML格式错误: {e.problem}"
            ))

    def _calculate_json_error_position(self, content: str, pos: int) -> Tuple[int, int]:
        """计算JSON错误位置"""
        if pos >= len(content):
            return 1, 1
            
        lines = content[:pos].split('\n')
        line_no = len(lines)
        char_pos = len(lines[-1]) + 1
        return line_no, char_pos

    def _calculate_yaml_error_position(self, file_path: Path, error: yaml.YAMLError) -> Tuple[int, int]:
        """计算YAML错误位置"""
        try:
            if hasattr(error, 'problem_mark'):
                mark = error.problem_mark
                return mark.line + 1, mark.column + 1
        except:
            pass
        return 1, 1

    def _validate_yaml_indentation(self, file_path: Path):
        """验证YAML文件缩进"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                
            for line_num, line in enumerate(lines, 1):
                if line.strip() and not line.startswith('#'):
                    # 检查缩进是否使用空格（不是tab）
                    if '\t' in line:
                        tab_pos = line.find('\t')
                        self.result.file_errors.append(FileError(
                            file_name=file_path.name,
                            line_number=line_num,
                            char_position=tab_pos + 1,
                            description="使用了Tab缩进，应该使用空格"
                        ))
                    
                    # 检查缩进是否一致（2的倍数）
                    indent = len(line) - len(line.lstrip())
                    if indent % 2 != 0 and indent > 0:
                        self.result.file_errors.append(FileError(
                            file_name=file_path.name,
                            line_number=line_num,
                            char_position=indent + 1,
                            description=f"缩进不是2的倍数 ({indent} 空格)"
                        ))
                        
        except Exception as e:
            self.result.file_errors.append(FileError(
                file_name=file_path.name,
                line_number=0,
                char_position=0,
                description=f"无法检查缩进: {e}"
            ))

    def _check_secret_manifest_validity(self):
        """2. 检查Secret Manifest合法性（placeholder）"""
        print("\n2. Secret Manifest合法性检查")
        
        if not self.secret_data:
            print("   ❌ 无法检查：secret.yml文件加载失败")
            return
            
        try:
            secret_content = self._read_file_content(self.secret_file)
            placeholders = self._extract_placeholders(secret_content)
            self.result.placeholder_count = len(placeholders)
            
            print(f"   检查了 {len(placeholders)} 个placeholder")
            
            # 检查placeholder标签完整性
            self._check_placeholder_tags(placeholders, secret_content)
            
            if not self.result.secret_key_errors:
                print("   ✅ 所有placeholder标签格式正确")
                
        except Exception as e:
            print(f"   ❌ 检查失败: {e}")

    def _extract_placeholders(self, content: str) -> List[str]:
        """提取所有placeholder内容"""
        placeholder_pattern = r'<ENAAS_PLACEHOLDER>(.*?)<ENAAS_PLACEHOLDER>'
        return re.findall(placeholder_pattern, content)

    def _check_placeholder_tags(self, placeholders: List[str], content: str):
        """检查placeholder标签完整性"""
        lines = content.split('\n')
        
        for line_num, line in enumerate(lines, 1):
            tags_in_line = line.count('<ENAAS_PLACEHOLDER>')
            if tags_in_line > 0 and tags_in_line % 2 != 0:
                # 找到第一个标签位置
                tag_pos = line.find('<ENAAS_PLACEHOLDER>')
                self.result.secret_key_errors.append(SecretKeyError(
                    file_name=self.secret_file.name,
                    line_number=line_num,
                    char_position=tag_pos + 1,
                    secret_name="",
                    secret_key="",
                    description="ENAAS_PLACEHOLDER标签不成对"
                ))

    def _check_secret_matching(self):
        """3. 检查secret匹配"""
        print("\n3. Secret匹配检查")
        
        if not self.enaas_data or not self.secret_data:
            print("   ❌ 无法检查：必要文件加载失败")
            return
            
        try:
            # 3.1 检查enaas.json结构
            if not self._validate_enaas_structure():
                return
                
            # 3.2 检查encodedKeys一致性
            self._check_encoded_keys_consistency()
            
            # 3.3 检查placeholder内容匹配
            self._check_placeholder_content_matching()
            
            if not self.result.secret_key_errors:
                print("   ✅ 所有secret配置都匹配")
                
        except Exception as e:
            print(f"   ❌ 检查失败: {e}")

    def _validate_enaas_structure(self) -> bool:
        """验证enaas.json结构"""
        required_keys = ['keys', 'autoKeys', 'encodedKeys']
        for key in required_keys:
            if key not in self.enaas_data:
                print(f"   ❌ enaas.json缺少必需的键: {key}")
                return False

        # 检查是否有至少一个AppCode配置
        if not self.enaas_data['keys']:
            print("   ❌ enaas.json中缺少AppCode配置")
            return False
            
        # 显示找到的AppCode
        app_codes = list(self.enaas_data['keys'].keys())
        print(f"   ✅ enaas.json结构完整，找到AppCode: {', '.join(app_codes)}")
        return True

    def _check_encoded_keys_consistency(self):
        """检查encodedKeys与keys的一致性"""
        keys_data = self.enaas_data.get('keys', {})
        encoded_keys_data = self.enaas_data.get('encodedKeys', {})
        
        checked_keys = 0
        for app_name, secret_configs in encoded_keys_data.items():
            if app_name not in keys_data:
                print(f"   ❌ encodedKeys中的应用 {app_name} 在keys中不存在")
                continue
                
            for secret_name, encoded_key_list in secret_configs.items():
                if secret_name not in keys_data[app_name]:
                    print(f"   ❌ encodedKeys中的secret {secret_name} 在keys中不存在")
                    continue
                    
                for encoded_key in encoded_key_list:
                    checked_keys += 1
                    if encoded_key not in keys_data[app_name][secret_name]:
                        print(f"   ❌ encodedKeys中的key {encoded_key} 在keys.{app_name}.{secret_name}中不存在")
                        
        print(f"   检查了 {checked_keys} 个encodedKeys")

    def _check_placeholder_content_matching(self):
        """检查placeholder内容是否与enaas.json匹配"""
        if not self.secret_data:
            return
            
        try:
            secret_content = self._read_file_content(self.secret_file)
            placeholders = self._extract_placeholders(secret_content)
            
            checked_keys = 0
            for placeholder in placeholders:
                checked_keys += 1
                if not self._validate_placeholder_content(placeholder):
                    # 找到placeholder在文件中的位置
                    line_num, char_pos = self._find_placeholder_position(placeholder, secret_content)
                    self.result.secret_key_errors.append(SecretKeyError(
                        file_name=self.secret_file.name,
                        line_number=line_num,
                        char_position=char_pos,
                        secret_name="",
                        secret_key=placeholder,
                        description="在enaas.json中未找到对应的配置"
                    ))
                    
            print(f"   检查了 {checked_keys} 个placeholder内容")
            
        except Exception as e:
            print(f"   ❌ placeholder内容检查失败: {e}")

    def _validate_placeholder_content(self, placeholder: str) -> bool:
        """验证单个placeholder内容"""
        # 检查是否为有效的keys placeholder (secretname_keyname)
        if self._is_valid_keys_placeholder(placeholder):
            return True
            
        # 检查是否为有效的autoKeys placeholder (keyname_value)
        if self._is_valid_auto_keys_placeholder(placeholder):
            return True
            
        return False

    def _is_valid_keys_placeholder(self, placeholder: str) -> bool:
        """检查是否为有效的keys placeholder"""
        if '_' not in placeholder:
            return False
            
        secret_name, key_name = placeholder.split('_', 1)
        
        for app_config in self.enaas_data.get('keys', {}).values():
            if secret_name in app_config and key_name in app_config[secret_name]:
                return True
        return False

    def _is_valid_auto_keys_placeholder(self, placeholder: str) -> bool:
        """检查是否为有效的autoKeys placeholder"""
        for auto_configs in self.enaas_data.get('autoKeys', {}).values():
            for key_name, value_list in auto_configs.items():
                for value in value_list:
                    expected_placeholder = f"{key_name}_{value}"
                    if placeholder == expected_placeholder:
                        return True
        return False

    def _find_placeholder_position(self, placeholder: str, content: str) -> Tuple[int, int]:
        """找到placeholder在文件中的位置"""
        lines = content.split('\n')
        for line_num, line in enumerate(lines, 1):
            if placeholder in line:
                char_pos = line.find(placeholder) + 1
                return line_num, char_pos
        return 1, 1

    def _check_secret_reference_validity(self):
        """4. 检查secret引用合法性"""
        print("\n4. Secret引用合法性检查")
        
        if not self.dc_file:
            print("   ⚠️  跳过：未提供dc.yml文件")
            return
            
        if not self.dc_data or not self.secret_data:
            print("   ❌ 无法检查：必要文件加载失败")
            return
            
        try:
            # 获取secret.yml中的metadata.name
            secret_name = self._get_secret_name()
            if not secret_name:
                return
                
            # 查找dc.yml中的secretRef引用
            secret_refs = self._find_secret_refs(self.dc_data)
            
            if not secret_refs:
                print("   ⚠️  dc.yml中未找到secretRef引用")
                return
                
            # 检查引用是否匹配
            ref_names = [ref[0] for ref in secret_refs]
            self.result.secret_ref_names = (secret_name, ", ".join(ref_names))
            
            all_match = all(ref_name == secret_name for ref_name in ref_names)
            self.result.secret_ref_match = all_match
            
            if all_match:
                print(f"   ✅ 引用匹配: secret.yml({secret_name}) = dc.yml({', '.join(ref_names)})")
            else:
                print(f"   ❌ 引用不匹配: secret.yml({secret_name}) ≠ dc.yml({', '.join(ref_names)})")
                
        except Exception as e:
            print(f"   ❌ 检查失败: {e}")

    def _get_secret_name(self) -> Optional[str]:
        """获取secret.yml中的metadata.name"""
        if self.secret_data and 'metadata' in self.secret_data:
            return self.secret_data['metadata'].get('name')
        print("   ❌ secret.yml中缺少metadata.name")
        return None

    def _find_secret_refs(self, obj: Any, path: str = "") -> List[Tuple[str, str]]:
        """递归查找所有secretRef引用"""
        secret_refs = []
        
        if isinstance(obj, dict):
            for key, value in obj.items():
                current_path = f"{path}.{key}" if path else key
                if key == 'secretRef' and isinstance(value, dict) and 'name' in value:
                    secret_refs.append((value['name'], current_path))
                else:
                    secret_refs.extend(self._find_secret_refs(value, current_path))
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                current_path = f"{path}[{i}]"
                secret_refs.extend(self._find_secret_refs(item, current_path))
                
        return secret_refs

    def _read_file_content(self, file_path: Path) -> str:
        """读取文件内容"""
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()

    def _print_results(self):
        """输出检查结果"""
        print("\n" + "=" * 60)
        print("检查结果汇总")
        print("=" * 60)
        
        if self.result.has_errors:
            print(f"❌ 发现 {self.result.total_errors} 个问题:")
            
            if self.result.file_errors:
                print("\n文件合法性问题:")
                for error in self.result.file_errors:
                    print(f"  - {error}")
                    
            if self.result.secret_key_errors:
                print("\nSecret配置问题:")
                for error in self.result.secret_key_errors:
                    print(f"  - {error}")
        else:
            print("✅ 所有检查都通过了!")
            
        # 显示统计信息
        print(f"\n📊 检查统计:")
        print(f"  - 检查的placeholder数量: {self.result.placeholder_count}")
        if self.dc_file:
            print(f"  - Secret引用匹配: {'✅ 是' if self.result.secret_ref_match else '❌ 否'}")
            if self.result.secret_ref_names[0]:
                print(f"  - Secret名称: {self.result.secret_ref_names[0]}")
                print(f"  - 引用名称: {self.result.secret_ref_names[1]}")


def main():
    """主函数"""
    # 检查是否是自动扫描模式
    if len(sys.argv) >= 2 and sys.argv[1] == "review openshift manifest":
        print("🔍 启动自动扫描模式...")
        
        # 检查是否指定了目标目录
        target_directory = None
        if len(sys.argv) == 3:
            target_directory = sys.argv[2]
            print(f"🎯 目标目录: {target_directory}")
        
        # 创建reviewer实例（文件路径不重要，因为我们使用自动扫描）
        reviewer = ENAASReviewerV2("dummy.json", "dummy.yml")
        reviewer.run_batch_review(target_directory)
        return
    
    # 手动指定文件模式
    if len(sys.argv) < 3 or len(sys.argv) > 4:
        print("用法:")
        print("  1. 自动扫描模式:")
        print("     python enaas_reviewer_v2.py 'review openshift manifest'                    # 扫描所有目录")
        print("     python enaas_reviewer_v2.py 'review openshift manifest' <目录名>          # 从根目录寻找并扫描指定目录")
        print("  2. 手动指定文件模式:")
        print("     python enaas_reviewer_v2.py <enaas.json路径> <*_secret.yml路径> [*_dc.yml路径]")
        print("")
        print("示例:")
        print("  # 自动扫描所有目录")
        print("  python enaas_reviewer_v2.py 'review openshift manifest'")
        print("")
        print("  # 从根目录寻找并扫描指定目录")
        print("  python enaas_reviewer_v2.py 'review openshift manifest' test-api")
        print("  python enaas_reviewer_v2.py 'review openshift manifest' cicdscript")
        print("")
        print("  # 手动检查特定文件")
        print("  python enaas_reviewer_v2.py enaas-details.json myapp_secret.yml")
        print("  python enaas_reviewer_v2.py enaas-details.json myapp_secret.yml myapp_dc.yml")
        sys.exit(1)

    enaas_file = sys.argv[1]
    secret_file = sys.argv[2]
    dc_file = sys.argv[3] if len(sys.argv) == 4 else None

    reviewer = ENAASReviewerV2(enaas_file, secret_file, dc_file)
    result = reviewer.run_review()

    sys.exit(0 if not result.has_errors else 1)


if __name__ == "__main__":
    main()
