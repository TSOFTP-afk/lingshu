<template>
  <el-dialog
    v-model="visible"
    title="视图设置"
    width="440px"
    @close="$emit('close')"
  >
    <el-form
      :model="form"
      label-width="80px"
      size="small"
    >
      <el-form-item label="主题">
        <el-select v-model="form.theme">
          <el-option
            v-for="(v, k) in themes.themes"
            :key="k"
            :label="v.label"
            :value="k"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="编辑器字号">
        <el-input-number
          v-model="form.fontSize"
          :min="11"
          :max="22"
          size="small"
        />
      </el-form-item>
      <el-form-item label="行高">
        <el-slider
          v-model="form.lineHeight"
          :min="120"
          :max="180"
          :step="5"
          show-input
          style="width:200px"
        />
        <span style="font-size:11px;color:var(--text-placeholder);margin-left:6px">%</span>
      </el-form-item>
      <el-form-item label="左侧宽度">
        <el-input-number
          v-model="form.leftWidth"
          :min="18"
          :max="35"
          size="small"
        />
      </el-form-item>
      <el-form-item label="右侧宽度">
        <el-input-number
          v-model="form.rightWidth"
          :min="20"
          :max="40"
          size="small"
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">
        取消
      </el-button>
      <el-button
        type="primary"
        @click="onSave"
      >
        保存
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { useThemeStore } from '../../stores/theme';

const props = defineProps({ modelValue: Boolean });
const emit = defineEmits(['update:modelValue', 'close']);

const visible = ref(props.modelValue);
watch(() => props.modelValue, v => { visible.value = v; });
watch(visible, v => emit('update:modelValue', v));

const themes = useThemeStore();

const form = ref({
  theme: localStorage.getItem('lingshu_theme') || 'white',
  fontSize: parseInt(localStorage.getItem('lingshu_font_size') || '14'),
  lineHeight: parseInt(localStorage.getItem('lingshu_line_height') || '145'),
  leftWidth: parseInt(localStorage.getItem('lingshu_left_width') || '22'),
  rightWidth: parseInt(localStorage.getItem('lingshu_right_width') || '28'),
});

function onSave() {
  themes.apply(form.value.theme);
  localStorage.setItem('lingshu_font_size', String(form.value.fontSize));
  localStorage.setItem('lingshu_line_height', String(form.value.lineHeight));
  localStorage.setItem('lingshu_left_width', String(form.value.leftWidth));
  localStorage.setItem('lingshu_right_width', String(form.value.rightWidth));
  ElMessage.success('视图设置已保存');
  document.documentElement.style.setProperty('--editor-font-size', form.value.fontSize + 'px');
  visible.value = false;
}
</script>
